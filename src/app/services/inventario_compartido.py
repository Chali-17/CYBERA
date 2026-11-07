"""Registro en memoria de la IP conocida de cada MAC (para el motor ARP).

El inventario de dispositivos detectados es temporal y no se persiste. El motor
de aislamiento por envenenamiento ARP necesita la IP del objetivo para dirigir
las tramas, pero ``IsolationService`` solo conoce la MAC. Este registro es un
punto de encuentro en memoria: ``MonitoringService`` publica, tras cada ciclo,
la relación MAC → IP detectada, y el motor la consulta justo antes de iniciar el
envenenamiento.

No guarda datos personales más allá del par IP/MAC ya presente en el inventario
temporal y se descarta junto con él.
"""

from __future__ import annotations

import threading

from app.models.dispositivo import PerfilDispositivo
from app.models.mac import normalizar_mac

_candado = threading.Lock()
_por_mac: dict[str, str] = {}


def publicar(perfiles: list[PerfilDispositivo]) -> None:
    """Actualiza la relación MAC → IP con los dispositivos de un ciclo."""
    with _candado:
        for perfil in perfiles:
            if not perfil.ip:
                continue
            try:
                _por_mac[normalizar_mac(perfil.mac)] = perfil.ip
            except ValueError:
                continue


def ip_de_mac(mac: str) -> str | None:
    """IP detectada más recientemente para ``mac``, o None si no se conoce."""
    try:
        clave = normalizar_mac(mac)
    except ValueError:
        return None
    with _candado:
        return _por_mac.get(clave)


def limpiar() -> None:
    """Descarta la relación (monitoreo desactivado o cierre)."""
    with _candado:
        _por_mac.clear()
