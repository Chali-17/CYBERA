"""Descubrimiento por ARP en Windows sin controladores adicionales.

Técnicas utilizadas (todas incluidas en Windows 10/11, sin Npcap):

1. ``SendARP`` (iphlpapi.dll): envía una solicitud ARP real a cada IP de la
   subred y devuelve la MAC si el equipo responde. ARP es obligatorio para
   comunicarse por IPv4 en la red local, por lo que también detecta equipos
   que bloquean ping (ICMP) con su firewall.
2. ``Get-NetNeighbor``: entradas de la tabla de vecinos que Windows marca
   como ``Reachable`` (confirmadas recientemente por el propio sistema).

No requieren privilegios de administrador.
"""

from __future__ import annotations

import ctypes
import socket
import struct
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from app.models.dispositivo import FuenteObservacion, ObservacionRed
from app.models.mac import es_mac_valida, normalizar_mac
from infrastructure.interfaces import IArpProbe
from infrastructure.network.powershell import ejecutar_json

_NO_ERROR = 0


def _ip_a_entero(ip: str) -> int:
    # IPAddr de Windows: dirección IPv4 en orden de red, leída como ULONG little-endian.
    return struct.unpack("<I", socket.inet_aton(ip))[0]


# La tabla de vecinos (Get-NetNeighbor, respaldada por CIM/WMI) puede bloquearse
# mucho en algunos entornos. Es una fuente COMPLEMENTARIA del barrido ARP activo,
# así que usa un timeout propio y corto, separado del timeout global de PowerShell.
TIMEOUT_VECINOS_POR_DEFECTO = 5.0


class WindowsArpProbe(IArpProbe):
    def __init__(self, hilos: int = 64, ejecutor_ps=ejecutar_json,
                 timeout_vecinos: float = TIMEOUT_VECINOS_POR_DEFECTO) -> None:
        self._hilos = hilos
        self._ejecutar_ps = ejecutor_ps
        self._timeout_vecinos = timeout_vecinos
        self._send_arp = None

    def _funcion_send_arp(self):
        if self._send_arp is None:
            if sys.platform != "win32":
                raise OSError("SendARP solo está disponible en Windows.")
            iphlpapi = ctypes.WinDLL("iphlpapi.dll")
            funcion = iphlpapi.SendARP
            funcion.argtypes = [ctypes.c_ulong, ctypes.c_ulong,
                                ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            funcion.restype = ctypes.c_ulong
            self._send_arp = funcion
        return self._send_arp

    def _consultar(self, ip: str, origen: int, cancelar: threading.Event) -> ObservacionRed | None:
        if cancelar.is_set():
            return None
        funcion = self._funcion_send_arp()
        buffer = (ctypes.c_ubyte * 8)()
        longitud = ctypes.c_ulong(ctypes.sizeof(buffer))
        resultado = funcion(_ip_a_entero(ip), origen, buffer, ctypes.byref(longitud))
        if resultado != _NO_ERROR or longitud.value != 6:
            return None  # Sin respuesta ARP (no se interpreta como «desconectado»).
        mac = ":".join(f"{b:02X}" for b in bytes(buffer)[:6])
        return ObservacionRed(ip=ip, mac=mac, fuente=FuenteObservacion.RESPUESTA_ARP)

    def sondear(self, ips: list[str], ip_origen: str,
                cancelar: threading.Event) -> list[ObservacionRed]:
        if not ips:
            return []
        origen = _ip_a_entero(ip_origen)
        self._funcion_send_arp()  # Falla pronto si no estamos en Windows.
        with ThreadPoolExecutor(max_workers=self._hilos,
                                thread_name_prefix="cybera-arp") as ejecutor:
            resultados = list(ejecutor.map(lambda ip: self._consultar(ip, origen, cancelar), ips))
        return [r for r in resultados if r is not None]

    def vecinos_alcanzables(self, indice_interfaz: int) -> list[ObservacionRed]:
        script = (
            f"$v = @(Get-NetNeighbor -AddressFamily IPv4 -InterfaceIndex {int(indice_interfaz)} "
            "-ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Reachable' } | "
            "Select-Object @{n='IP';e={[string]$_.IPAddress}}, "
            "@{n='Mac';e={[string]$_.LinkLayerAddress}}); "
            "ConvertTo-Json -InputObject $v -Compress"
        )
        observaciones = []
        # Timeout corto propio: si Get-NetNeighbor se agota, la llamada lanza
        # PowerShellError y el descubrimiento continúa con el barrido ARP activo.
        for registro in self._ejecutar_ps(script, timeout=self._timeout_vecinos):
            mac, ip = registro.get("Mac"), registro.get("IP")
            if ip and mac and es_mac_valida(mac):
                observaciones.append(ObservacionRed(
                    ip=ip, mac=normalizar_mac(mac), fuente=FuenteObservacion.VECINO_ALCANZABLE))
        return observaciones
