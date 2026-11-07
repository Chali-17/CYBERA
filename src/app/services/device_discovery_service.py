"""DeviceDiscoveryService: observaciones de red → perfiles enriquecidos (RF01, CU-03).

Flujo por ciclo, limitado a la interfaz seleccionada:
1. Barrido ARP activo de la subred IPv4 de la interfaz (si su tamaño lo permite).
2. Entradas «Reachable» de la tabla de vecinos de esa misma interfaz.
3. Unión por MAC, descartando direcciones que no identifican a un equipo.
4. Fabricante por OUI (solo MAC universales) y hostname por resolución inversa.

Ningún dato se inventa: lo que no se obtiene queda en None.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime

from app.models.dispositivo import FuenteObservacion, ObservacionRed, PerfilDispositivo
from app.models.interfaz_red import InterfazRed
from app.models.mac import es_administrada_localmente, es_mac_de_dispositivo, normalizar_mac
from infrastructure.interfaces import IArpProbe, IHostnameResolver, IOuiResolver
from infrastructure.network.powershell import PowerShellError

_log = logging.getLogger(__name__)

# Subredes más grandes que /22 (1022 hosts) no se barren activamente: tardaría
# demasiado y generaría mucho tráfico. Se usa solo la tabla de vecinos.
PREFIJO_MINIMO_BARRIDO = 22


class InterfazNoDisponibleError(RuntimeError):
    pass


@dataclass
class ResultadoDescubrimiento:
    interfaz: InterfazRed
    red: ipaddress.IPv4Network
    perfiles: list[PerfilDispositivo] = field(default_factory=list)
    hosts_sondeados: int = 0
    barrido_activo: bool = False
    cancelado: bool = False


class DeviceDiscoveryService:
    def __init__(self, sonda: IArpProbe, oui: IOuiResolver, hostnames: IHostnameResolver,
                 nombre_equipo: str | None = None,
                 reloj: Callable[[], datetime] = datetime.now,
                 tiempo_maximo_hostname: float = 6.0,
                 vigencia_cache_hostname: float = 600.0) -> None:
        self._sonda = sonda
        self._oui = oui
        self._hostnames = hostnames
        self._nombre_equipo = nombre_equipo
        self._reloj = reloj
        self._tiempo_hostname = tiempo_maximo_hostname
        self._vigencia_cache = vigencia_cache_hostname
        # Caché en memoria (no persistente): (ip, mac) -> (nombre | None, instante)
        self._cache_hostname: dict[tuple[str, str], tuple[str | None, float]] = {}
        self._lock_cache = threading.Lock()

    def descubrir(self, interfaz: InterfazRed, cancelar: threading.Event) -> ResultadoDescubrimiento:
        motivo = interfaz.motivo_no_utilizable()
        if motivo:
            raise InterfazNoDisponibleError(motivo)
        red = interfaz.red
        resultado = ResultadoDescubrimiento(interfaz=interfaz, red=red)

        observaciones: list[ObservacionRed] = []
        if red.prefixlen >= PREFIJO_MINIMO_BARRIDO:
            objetivos = [str(h) for h in red.hosts()]
            resultado.barrido_activo = True
            resultado.hosts_sondeados = len(objetivos)
            observaciones += self._sonda.sondear(objetivos, interfaz.ipv4, cancelar)
        if cancelar.is_set():
            resultado.cancelado = True
            return resultado
        # Fuente COMPLEMENTARIA (tabla de vecinos, vía PowerShell). Si se agota o
        # falla, NO debe derribar el ciclo: se registra y el descubrimiento continúa
        # con el barrido ARP activo. Solo se captura PowerShellError (recuperable);
        # otros errores se propagan para no ocultar fallos no recuperables.
        try:
            observaciones += self._sonda.vecinos_alcanzables(interfaz.indice)
        except PowerShellError as error:
            _log.warning("No se pudo consultar la tabla de vecinos de la interfaz %s; "
                         "el descubrimiento continúa con el barrido ARP activo: %s",
                         interfaz.indice, error)
        if interfaz.mac:
            observaciones.append(ObservacionRed(interfaz.ipv4, interfaz.mac,
                                                FuenteObservacion.INTERFAZ_LOCAL))

        por_mac = self._unir(observaciones, red)
        ahora = self._reloj().replace(microsecond=0)
        perfiles = []
        for mac, obs in por_mac.items():
            perfiles.append(PerfilDispositivo(
                mac=mac,
                ip=obs.ip,
                primera_deteccion=ahora,
                ultima_deteccion=ahora,
                fabricante=None if es_administrada_localmente(mac) else self._oui.fabricante(mac),
                fuente=obs.fuente,
                es_este_equipo=(obs.ip == interfaz.ipv4),
                es_puerta_enlace=(obs.ip == interfaz.puerta_enlace),
            ))
        self._asignar_hostnames(perfiles, cancelar)
        if cancelar.is_set():
            resultado.cancelado = True
            return resultado
        resultado.perfiles = perfiles
        return resultado

    @staticmethod
    def _unir(observaciones: list[ObservacionRed],
              red: ipaddress.IPv4Network) -> dict[str, ObservacionRed]:
        por_mac: dict[str, ObservacionRed] = {}
        for obs in observaciones:
            if not es_mac_de_dispositivo(obs.mac):
                continue  # Difusión, multicast o MAC nula.
            try:
                ip = ipaddress.ip_address(obs.ip)
            except ValueError:
                continue
            if ip not in red or ip in (red.network_address, red.broadcast_address):
                continue
            mac = normalizar_mac(obs.mac)
            # La respuesta ARP del ciclo actual es la evidencia más directa: se conserva.
            if mac not in por_mac or obs.fuente is FuenteObservacion.RESPUESTA_ARP:
                por_mac[mac] = ObservacionRed(obs.ip, mac, obs.fuente)
        return por_mac

    def _asignar_hostnames(self, perfiles: list[PerfilDispositivo], cancelar: threading.Event) -> None:
        ahora = time.monotonic()
        pendientes: list[PerfilDispositivo] = []
        with self._lock_cache:
            for perfil in perfiles:
                if perfil.es_este_equipo and self._nombre_equipo:
                    perfil.hostname = self._nombre_equipo
                    continue
                guardado = self._cache_hostname.get((perfil.ip, perfil.mac))
                if guardado and ahora - guardado[1] < self._vigencia_cache:
                    perfil.hostname = guardado[0]
                else:
                    pendientes.append(perfil)
        if not pendientes or cancelar.is_set():
            return
        ejecutor = ThreadPoolExecutor(max_workers=min(16, len(pendientes)),
                                      thread_name_prefix="cybera-host")
        try:
            futuros = {ejecutor.submit(self._hostnames.resolver, p.ip): p for p in pendientes}
            terminados, _ = wait(futuros, timeout=self._tiempo_hostname)
            with self._lock_cache:
                for futuro in terminados:
                    perfil = futuros[futuro]
                    try:
                        nombre = futuro.result()
                    except Exception:  # noqa: BLE001 - un fallo de nombre no detiene el ciclo
                        nombre = None
                    perfil.hostname = nombre
                    self._cache_hostname[(perfil.ip, perfil.mac)] = (nombre, ahora)
                # Los que no respondieron a tiempo quedan sin hostname en este ciclo.
        finally:
            ejecutor.shutdown(wait=False, cancel_futures=True)
