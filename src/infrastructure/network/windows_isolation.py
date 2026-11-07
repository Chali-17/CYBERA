"""WindowsIsolationEngine: motor de aislamiento de Capa 2 para Windows.

CONCLUSIÓN DE VIABILIDAD (ver docs/INFORME_MOTOR_AISLAMIENTO.md):

En una red doméstica conmutada, sin control del router ni del conmutador/punto
de acceso, NO existe en Windows un mecanismo de contención selectiva de OTRO
dispositivo que sea a la vez fiable y con recuperación controlada:

- El firewall de Windows (netsh/WFP) solo filtra el tráfico de ESTE equipo; no
  puede cortar el tráfico entre el intruso y el router.
- Aplicar una regla en el router o en el conmutador sí funcionaría, pero exige
  infraestructura gestionada y queda fuera del alcance (no depender del router).
- El envenenamiento de caché ARP es una técnica de ATAQUE (denegación de
  servicio dirigida), no fiable y sin recuperación garantizable; por contrato
  (ver INetworkIsolation y el informe) NO se implementa.

Por tanto este motor implementa el contrato ``INetworkIsolation`` de forma
HONESTA: se declara NO DISPONIBLE. Así la cadena de aislamiento queda integrada y
probada de extremo a extremo, pero la aplicación nunca afirma haber aislado nada.

Comportamiento (cumple el contrato):

- ``disponible()``: devuelve False siempre, sin tocar la red y sin excepciones.
  El motivo exacto queda en ``motivo_no_disponible`` (y en el registro).
- ``isolate``/``release``: lanzan ``OperacionNoEjecutadaError``. El contrato
  garantiza que eso significa «no se tocó la red», así que IsolationService lo
  trata como un fallo CONOCIDO (FAILED), nunca como un resultado incierto.
- ``status``: devuelve ``DESCONOCIDO`` (no hay evidencia de contención).

El motor es sin estado: las operaciones sobre MAC distintas son independientes y
``status``/``disponible`` no tienen efectos secundarios.
"""

from __future__ import annotations

import ctypes
import logging

import threading

from app.models.mac import es_mac_de_dispositivo
from infrastructure.interfaces import EstadoContencion, INetworkIsolation, OperacionNoEjecutadaError
from infrastructure.network.transmision_arp import (Emisor, ResultadoTransmision,
                                                    TrabajoTransmision, probar_transmision_arp,
                                                    probar_transmision_async)

_log = logging.getLogger(__name__)

_MOTIVO = (
    "No hay un mecanismo de contención selectiva seguro y recuperable en esta red. "
    "El firewall de Windows solo filtra el tráfico de este equipo, no el de otro "
    "dispositivo; aislar en Capa 2 exigiría control del router o del conmutador "
    "(fuera de alcance), y el envenenamiento ARP es una técnica de ataque sin "
    "recuperación garantizable, por lo que no se implementa.")


def _es_administrador() -> bool:
    """True si el proceso tiene privilegios de administrador (solo diagnóstico)."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - fuera de Windows o API no disponible
        return False


class WindowsIsolationEngine(INetworkIsolation):
    """Adaptador real para Windows. Honesto: no aplica contención (ver módulo)."""

    def __init__(self) -> None:
        self._diagnostico_emitido = False
        self._ultima_transmision: ResultadoTransmision | None = None

    @property
    def ultima_transmision(self) -> ResultadoTransmision | None:
        """Resultado de la última prueba de transmisión benigna, si se ejecutó."""
        return self._ultima_transmision

    @property
    def motivo_no_disponible(self) -> str:
        detalle = ("con privilegios de administrador" if _es_administrador()
                   else "sin privilegios de administrador")
        return (f"{_MOTIVO} (El proceso se ejecuta {detalle}; aun con privilegios, el "
                "mecanismo seguiría sin existir en esta topología de red.)")

    def probar_transmision(self, ip_objetivo: str, ip_interfaz: str, timeout: float = 2.0,
                           cancelar: threading.Event | None = None,
                           emisor: Emisor | None = None) -> ResultadoTransmision:
        """Diagnóstico: envía una solicitud ARP BENIGNA (no suplantada) y registra
        el resultado. NO habilita el aislamiento: transmitir una trama no permite
        contener a otro equipo. ``disponible()`` sigue devolviendo False."""
        resultado = probar_transmision_arp(ip_objetivo, ip_interfaz, timeout, cancelar, emisor)
        self._registrar_transmision(resultado)
        return resultado

    def probar_transmision_async(self, ip_objetivo: str, ip_interfaz: str, timeout: float = 2.0,
                                 cancelar: threading.Event | None = None,
                                 emisor: Emisor | None = None,
                                 al_terminar=None) -> TrabajoTransmision:
        """Igual que ``probar_transmision`` pero en segundo plano (no bloquea).
        Registra el resultado al terminar. No habilita el aislamiento."""
        def guardar(resultado: ResultadoTransmision) -> None:
            self._registrar_transmision(resultado)
            if al_terminar is not None:
                al_terminar(resultado)

        return probar_transmision_async(ip_objetivo, ip_interfaz, timeout, cancelar, emisor, guardar)

    def _registrar_transmision(self, resultado: ResultadoTransmision) -> None:
        self._ultima_transmision = resultado
        _log.info("Prueba de transmisión ARP hacia %s: %s (%.3fs) — %s",
                  resultado.ip_objetivo, resultado.estado.value, resultado.duracion_s,
                  resultado.detalle)

    def disponible(self) -> bool:
        if not self._diagnostico_emitido:
            # Se registra una sola vez, sin datos personales: solo el motivo técnico.
            _log.info("WindowsIsolationEngine no disponible: %s", self.motivo_no_disponible)
            self._diagnostico_emitido = True
        return False

    def isolate(self, mac: str) -> None:
        self._rechazar("aislar", mac)

    def release(self, mac: str) -> None:
        self._rechazar("desbloquear", mac)

    def status(self, mac: str) -> EstadoContencion:
        # Sin evidencia de contención: DESCONOCIDO (nunca SIN_CONTENCION por defecto).
        return EstadoContencion.DESCONOCIDO

    def _rechazar(self, accion: str, mac: str) -> None:
        # ``es_mac_de_dispositivo`` valida la entrada sin efectos de red.
        valida = es_mac_de_dispositivo(mac)
        _log.debug("Operación «%s» rechazada (motor no disponible, MAC válida=%s).",
                   accion, valida)
        # OperacionNoEjecutadaError = el contrato garantiza que NO se tocó la red.
        raise OperacionNoEjecutadaError(
            f"No se ejecutó la contención: {self.motivo_no_disponible}")
