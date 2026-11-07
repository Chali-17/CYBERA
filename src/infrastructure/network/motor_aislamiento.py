"""Selección del motor de aislamiento que usa la aplicación.

Por defecto se inyecta ``ArpSpoofingIsolationEngine`` (motor real por
envenenamiento ARP dirigido a agujero negro). Solo se activa de verdad si el
equipo cumple los requisitos (Windows, administrador, Npcap y una interfaz
conectada); si no, ``disponible()`` devuelve False y «Aislar» informa «no
disponible» sin tocar la red (ver ``arp_spoofing``).

La variable de entorno ``CYBERA_MOTOR`` permite elegir:

- ``arp`` (o sin definir): motor real de envenenamiento ARP.
- ``windows``: motor honesto que se declara NO DISPONIBLE
  (``WindowsIsolationEngine``), sin tocar la red.
- ``ninguno``: sin motor (``None``); el aislamiento informa «no disponible».
"""

from __future__ import annotations

import os

from infrastructure.interfaces import INetworkIsolation
from infrastructure.network.arp_spoofing import ArpSpoofingIsolationEngine
from infrastructure.network.windows_isolation import WindowsIsolationEngine

VARIABLE_MOTOR = "CYBERA_MOTOR"


def crear_motor() -> INetworkIsolation | None:
    seleccion = (os.environ.get(VARIABLE_MOTOR) or "arp").strip().lower()
    if seleccion in ("ninguno", "none", ""):
        return None
    if seleccion in ("windows", "honesto"):
        return WindowsIsolationEngine()
    return ArpSpoofingIsolationEngine()
