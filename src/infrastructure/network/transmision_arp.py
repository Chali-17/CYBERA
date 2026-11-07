"""Prueba de transmisión BENIGNA de una trama ARP (Windows/Scapy/Npcap).

Verifica empíricamente si el equipo puede transmitir una trama ARP construida,
enviando una **solicitud ARP estándar** («who-has», opcode 1) con la **MAC y la IP
propias del adaptador** como origen. Es exactamente lo que hace el sistema
operativo para resolver direcciones: NO suplanta direcciones, NO envenena cachés y
NO interrumpe a ningún equipo. Pensada para un entorno de laboratorio controlado.

Transmitir una trama NO es contener a otro equipo: esto no habilita el aislamiento
(ver WindowsIsolationEngine). Aquí NO hay ningún bucle de envenenamiento ARP.

Estados honestos del resultado:

- ``EXITO``:       se recibió la respuesta ARP → transmisión y recepción
                   confirmadas (ida y vuelta real).
- ``DESCONOCIDO``: la trama se entregó al socket sin error, pero no hubo
                   respuesta → no hay evidencia de ida y vuelta. No se afirma nada.
- ``FALLO``:       el envío falló (sin privilegios, Npcap, o el adaptador lo
                   rechazó).
- ``CANCELADO``:   se canceló antes de enviar o mientras se esperaba la respuesta.

Partes seguras implementadas: ejecución asíncrona (``probar_transmision_async``),
cancelación fiable (se comprueba cada ``PASO_SONDEO`` s), registro de errores,
resultados verificables (incluye duración) y recuperación de recursos (el socket
se cierra siempre; el hilo de fondo siempre termina y fija un resultado).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

_log = logging.getLogger(__name__)

# Tiempo máximo de una prueba (acotado) y granularidad del sondeo de cancelación.
TIMEOUT_POR_DEFECTO = 2.0
PASO_SONDEO = 0.2


class EstadoTransmision(Enum):
    EXITO = "EXITO"
    DESCONOCIDO = "DESCONOCIDO"
    FALLO = "FALLO"
    CANCELADO = "CANCELADO"


@dataclass(frozen=True)
class ResultadoTransmision:
    estado: EstadoTransmision
    ip_objetivo: str
    ip_interfaz: str
    detalle: str
    mac_resuelta: str | None = None   # MAC del objetivo si respondió.
    duracion_s: float = 0.0           # Tiempo real de la prueba (verificable).

    @property
    def exito(self) -> bool:
        return self.estado is EstadoTransmision.EXITO


# Emisor inyectable para las pruebas. Firma:
#   (ip_objetivo, ip_interfaz, timeout, cancelar) -> MAC respondida o None.
# Debe ser cooperativo con ``cancelar`` para que la cancelación sea fiable.
Emisor = Callable[[str, str, float, "threading.Event | None"], "str | None"]


def probar_transmision_arp(ip_objetivo: str, ip_interfaz: str,
                           timeout: float = TIMEOUT_POR_DEFECTO,
                           cancelar: threading.Event | None = None,
                           emisor: Emisor | None = None) -> ResultadoTransmision:
    """Envía una solicitud ARP benigna y clasifica el resultado de forma honesta.

    ``emisor`` permite inyectar un doble en las pruebas; por defecto usa
    Scapy/Npcap (``_emisor_scapy``). Nunca lanza: cualquier fallo se convierte en
    un resultado ``FALLO`` (recuperación de recursos garantizada por el emisor).
    """
    inicio = time.monotonic()

    def construir(estado, detalle, mac=None):
        return ResultadoTransmision(estado, ip_objetivo, ip_interfaz, detalle, mac,
                                    round(time.monotonic() - inicio, 3))

    if cancelar is not None and cancelar.is_set():
        return construir(EstadoTransmision.CANCELADO, "Cancelado antes de transmitir.")

    enviar = emisor or _emisor_scapy
    try:
        mac = enviar(ip_objetivo, ip_interfaz, timeout, cancelar)
    except Exception as error:  # noqa: BLE001 - cualquier fallo del backend de envío
        _log.warning("Transmisión ARP hacia %s por %s falló: %s", ip_objetivo, ip_interfaz, error)
        return construir(EstadoTransmision.FALLO, f"No se pudo transmitir: {error}")

    if cancelar is not None and cancelar.is_set():
        return construir(EstadoTransmision.CANCELADO, "Cancelado durante la transmisión.")
    if mac is None:
        return construir(EstadoTransmision.DESCONOCIDO,
                         "Se entregó la trama al socket, pero no hubo respuesta: sin evidencia "
                         "de ida y vuelta.")
    return construir(EstadoTransmision.EXITO,
                     f"Transmisión y respuesta confirmadas; {ip_objetivo} respondió.", mac)


class TrabajoTransmision:
    """Prueba de transmisión en segundo plano. Recuperación de recursos: el hilo
    es demonio, siempre termina y siempre deja un ``resultado`` (incluso ante
    error o cancelación)."""

    def __init__(self, hilo: threading.Thread, cancelar: threading.Event,
                 contenedor: dict) -> None:
        self._hilo = hilo
        self._cancelar = cancelar
        self._contenedor = contenedor

    def cancelar(self) -> None:
        self._cancelar.set()

    def hecho(self) -> bool:
        return not self._hilo.is_alive()

    def esperar(self, timeout: float | None = None) -> ResultadoTransmision | None:
        self._hilo.join(timeout)
        return self._contenedor.get("resultado")

    @property
    def resultado(self) -> ResultadoTransmision | None:
        return self._contenedor.get("resultado")


def probar_transmision_async(ip_objetivo: str, ip_interfaz: str,
                             timeout: float = TIMEOUT_POR_DEFECTO,
                             cancelar: threading.Event | None = None,
                             emisor: Emisor | None = None,
                             al_terminar: Callable[[ResultadoTransmision], None] | None = None,
                             ) -> TrabajoTransmision:
    """Ejecuta ``probar_transmision_arp`` en un hilo de fondo. Devuelve de
    inmediato un ``TrabajoTransmision`` para cancelar y recoger el resultado.

    En la interfaz PySide6 puede usarse igualmente envolviendo
    ``WindowsIsolationEngine.probar_transmision`` en un ``TareaFondo``; este
    runner es independiente de Qt para poder probarse de forma determinista.
    """
    cancelar = cancelar or threading.Event()
    contenedor: dict = {}

    def correr() -> None:
        resultado = probar_transmision_arp(ip_objetivo, ip_interfaz, timeout, cancelar, emisor)
        contenedor["resultado"] = resultado           # Siempre se fija un resultado.
        if al_terminar is not None:
            try:
                al_terminar(resultado)
            except Exception:  # noqa: BLE001 - un callback no debe tumbar el hilo
                _log.exception("El callback de transmisión falló")

    hilo = threading.Thread(target=correr, name="transmision-arp", daemon=True)
    hilo.start()
    return TrabajoTransmision(hilo, cancelar, contenedor)


def _emisor_scapy(ip_objetivo: str, ip_interfaz: str, timeout: float,
                  cancelar: threading.Event | None = None) -> str | None:
    """Envía una solicitud ARP estándar (no suplantada) con Scapy/Npcap.

    MAC e IP de origen son las PROPIAS del adaptador. Reenvía la solicitud en
    pasos cortos hasta ``timeout`` (comportamiento normal de reintento de ARP),
    comprobando la cancelación en cada paso. Devuelve la MAC del objetivo si
    respondió, o None. Lanza excepción si no se pudo transmitir. Scapy abre y
    cierra su propio socket en cada ``srp1`` (recuperación de recursos).
    """
    import os
    os.environ.setdefault("SCAPY_USE_LIBPCAP", "yes")
    import warnings
    warnings.filterwarnings("ignore")
    from scapy.all import ARP, Ether, get_working_ifaces, srp1

    iface = next((i for i in get_working_ifaces() if getattr(i, "ip", None) == ip_interfaz), None)
    if iface is None:
        raise RuntimeError(f"No se encontró una interfaz con IP {ip_interfaz}.")
    mi_mac = getattr(iface, "mac", None)
    if not mi_mac:
        raise RuntimeError("La interfaz no tiene una MAC utilizable.")

    # Solicitud ARP legítima «who-has»: origen = el propio adaptador (sin suplantar).
    trama = (Ether(src=mi_mac, dst="ff:ff:ff:ff:ff:ff")
             / ARP(op=1, hwsrc=mi_mac, psrc=ip_interfaz, pdst=ip_objetivo))
    restante = timeout
    while restante > 0:
        if cancelar is not None and cancelar.is_set():
            return None
        paso = min(PASO_SONDEO, restante)
        respuesta = srp1(trama, iface=iface, timeout=paso, verbose=0)
        if respuesta is not None:
            return respuesta[ARP].hwsrc
        restante -= paso
    return None
