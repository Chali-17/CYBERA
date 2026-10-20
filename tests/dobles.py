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
