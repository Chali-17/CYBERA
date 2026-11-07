"""Dobles de prueba: sustituyen la red real para probar la lógica de forma determinista.

Las direcciones de estos dobles son datos de PRUEBA, nunca se muestran en la
aplicación real.
"""

from __future__ import annotations

import threading
import time

from app.models.dispositivo import FuenteObservacion, ObservacionRed
from app.models.interfaz_red import InterfazRed, TipoInterfaz
from infrastructure.interfaces import (IArpProbe, IHostnameResolver, INetworkInterface,
                                       IOuiResolver)


def interfaz(id_="{GUID-WIFI}", nombre="Wi-Fi", ip="10.0.0.5", prefijo=24, conectada=True,
             puerta="10.0.0.1", mac="02:00:00:00:00:05", indice=7, tipo=TipoInterfaz.WIFI):
    return InterfazRed(id=id_, indice=indice, nombre=nombre, descripcion="Adaptador de prueba",
                       tipo=tipo, conectada=conectada, mac=mac, ipv4=ip, prefijo=prefijo,
                       puerta_enlace=puerta)


class ProveedorInterfacesFalso(INetworkInterface):
    def __init__(self, interfaces):
        self.interfaces = list(interfaces)
        self.llamadas = 0

    def list_interfaces(self):
        self.llamadas += 1
        return list(self.interfaces)


class SondaFalsa(IArpProbe):
    def __init__(self, respuestas=None, vecinos=None, demora=0.0):
        self.respuestas = dict(respuestas or {})   # ip -> mac
        self.vecinos = dict(vecinos or {})         # ip -> mac
        self.demora = demora
        self.sondeos: list[tuple[list[str], str]] = []

    def sondear(self, ips, ip_origen, cancelar: threading.Event):
        self.sondeos.append((list(ips), ip_origen))
        fin = time.monotonic() + self.demora
        while time.monotonic() < fin:
            if cancelar.is_set():
                return []
            time.sleep(0.01)
        return [ObservacionRed(ip, mac, FuenteObservacion.RESPUESTA_ARP)
                for ip, mac in self.respuestas.items() if ip in ips]

    def vecinos_alcanzables(self, indice_interfaz):
        return [ObservacionRed(ip, mac, FuenteObservacion.VECINO_ALCANZABLE)
                for ip, mac in self.vecinos.items()]


class OuiFalso(IOuiResolver):
    def __init__(self, tabla=None):
        self.tabla = tabla or {}

    def fabricante(self, mac):
        return self.tabla.get(mac[:8])


class HostnamesFalso(IHostnameResolver):
    def __init__(self, nombres=None, lentos=(), demora=5.0):
        self.nombres = nombres or {}
        self.lentos = set(lentos)
        self.demora = demora
        self.consultas: list[str] = []

    def resolver(self, ip):
        self.consultas.append(ip)
        if ip in self.lentos:
            time.sleep(self.demora)
        return self.nombres.get(ip)


class MotorSimulado:
    """Motor de aislamiento SIMULADO (INetworkIsolation) para las pruebas.

    No toca la red: guarda en memoria qué MAC «aislaría». Permite forzar
    errores, respuestas sin confirmación, indisponibilidad y bloquear una
    llamada hasta que la prueba lo libere (para probar concurrencia).
    """

    def __init__(self, *, confirma_aislar=True, confirma_liberar=True, falla_isolate=False,
                 falla_release=False, falla_status=False, estado_forzado=None, disponible=True,
                 restaura_desconocidas=False, no_ejecuta=False):
        from infrastructure.interfaces import EstadoContencion
        self._Estado = EstadoContencion
        self.confirma_aislar = confirma_aislar
        self.confirma_liberar = confirma_liberar
        self.falla_isolate = falla_isolate
        self.falla_release = falla_release
        self.falla_status = falla_status
        self.estado_forzado = estado_forzado
        self.operativo = disponible
        # Motor RESTAURADOR (contrato): release retira también contenciones que no
        # conoce (p. ej. de una ejecución anterior) y luego puede afirmarlo.
        self.restaura_desconocidas = restaura_desconocidas
        # Simula una comprobación previa fallida: el motor garantiza no tocar la red.
        self.no_ejecuta = no_ejecuta
        self.aisladas: set[str] = set()
        # MAC sobre las que el motor actuó en ESTA vida del doble. Las demás son
        # desconocidas y status() devuelve DESCONOCIDO (contrato H3).
        self.conocidas: set[str] = set()
        self.llamadas: list[tuple[str, str]] = []
        self.bloqueos: dict[str, threading.Event] = {}   # mac -> evento que hay que esperar
        self.dentro: dict[str, threading.Event] = {}     # mac -> señal «ya entró al motor»
        self._candado = threading.Lock()

    def bloquear(self, mac):
        self.bloqueos[mac] = threading.Event()
        self.dentro[mac] = threading.Event()
        return self.bloqueos[mac]

    def _esperar(self, mac):
        if mac in self.dentro:
            self.dentro[mac].set()
        if mac in self.bloqueos:
            assert self.bloqueos[mac].wait(5), "la prueba no liberó el motor"

    def disponible(self):
        return self.operativo

    def isolate(self, mac):
        with self._candado:
            self.llamadas.append(("isolate", mac))
        self._esperar(mac)
        if self.no_ejecuta:
            from infrastructure.interfaces import OperacionNoEjecutadaError
            raise OperacionNoEjecutadaError("comprobación previa fallida; no se envió nada")
        if self.falla_isolate:
            raise OSError("se requieren privilegios de administrador")
        self.conocidas.add(mac)
        if self.confirma_aislar:
            self.aisladas.add(mac)

    def release(self, mac):
        with self._candado:
            self.llamadas.append(("release", mac))
        self._esperar(mac)
        if self.no_ejecuta:
            from infrastructure.interfaces import OperacionNoEjecutadaError
            raise OperacionNoEjecutadaError("comprobación previa fallida; no se envió nada")
        if self.falla_release:
            raise OSError("no se pudo restaurar la tabla ARP")
        if self.restaura_desconocidas:
            self.conocidas.add(mac)
        if self.confirma_liberar and mac in self.conocidas:
            self.aisladas.discard(mac)

    def status(self, mac):
        if self.falla_status:
            raise TimeoutError("el motor no respondió")
        if self.estado_forzado is not None:
            return self.estado_forzado
        if mac in self.aisladas:
            return self._Estado.CONTENCION_APLICADA
        if mac in self.conocidas:
            return self._Estado.SIN_CONTENCION
        return self._Estado.DESCONOCIDO
