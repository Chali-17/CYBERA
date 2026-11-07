"""Pruebas del descubrimiento ante fallos de PowerShell (ERROR 1).

Un timeout o fallo de PowerShell en la fuente COMPLEMENTARIA (tabla de vecinos,
``vecinos_alcanzables``) no debe derribar el ciclo: se registra y el
descubrimiento continúa con el barrido ARP activo. Se simula ``TimeoutExpired``
sin tocar la red.
"""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime

import pytest

from app.models.dispositivo import FuenteObservacion, ObservacionRed
from app.services.device_discovery_service import DeviceDiscoveryService
from dobles import HostnamesFalso, OuiFalso, SondaFalsa, interfaz
from infrastructure.interfaces import IArpProbe
from infrastructure.network.powershell import PowerShellError, ejecutar_json

MAC_PC = "50:9A:4C:4C:78:B2"
T0 = datetime(2026, 10, 21, 9, 0, 0)


# --- Origen del fallo: ejecutar_json convierte TimeoutExpired en PowerShellError ---

def test_timeout_de_powershell_se_convierte_en_powershellerror(monkeypatch):
    def run_que_se_agota(*a, **k):
        raise subprocess.TimeoutExpired(cmd="powershell.exe", timeout=30)

    monkeypatch.setattr(subprocess, "run", run_que_se_agota)
    with pytest.raises(PowerShellError):
        ejecutar_json("Get-NetNeighbor", timeout=0.1)


# --- El servicio tolera el fallo de la fuente complementaria ---------------------

class SondaVecinosFallan(SondaFalsa):
    """Sonda cuyo barrido ARP funciona pero cuya tabla de vecinos agota PowerShell."""

    def vecinos_alcanzables(self, indice_interfaz):
        raise PowerShellError("PowerShell no respondió a tiempo.")


def _servicio(sonda: IArpProbe) -> DeviceDiscoveryService:
    return DeviceDiscoveryService(sonda, OuiFalso(), HostnamesFalso(),
                                  tiempo_maximo_hostname=0.1, reloj=lambda: T0)


def test_fallo_de_vecinos_no_derriba_el_descubrimiento(caplog):
    # El barrido ARP activo sí detecta un equipo; los vecinos fallan.
    sonda = SondaVecinosFallan({"10.0.0.14": MAC_PC})
    resultado = _servicio(sonda).descubrir(interfaz(), threading.Event())
    macs = {p.mac for p in resultado.perfiles}
    assert MAC_PC in macs                               # El ciclo continúa y entrega datos reales.
    assert any("tabla de vecinos" in r.message for r in caplog.records)   # Se registró el fallo.


def test_sin_barrido_ni_vecinos_no_inventa_dispositivos():
    # Barrido vacío y vecinos que fallan: resultado sin dispositivos (no se inventa nada).
    sonda = SondaVecinosFallan(respuestas={})
    resultado = _servicio(sonda).descubrir(interfaz(), threading.Event())
    detectadas = {p.mac for p in resultado.perfiles if p.fuente is not FuenteObservacion.INTERFAZ_LOCAL}
    assert detectadas == set()


def test_error_no_recuperable_de_vecinos_se_propaga():
    # Un error que NO es de PowerShell no debe ocultarse.
    class SondaRompe(SondaFalsa):
        def vecinos_alcanzables(self, indice_interfaz):
            raise RuntimeError("fallo de programación inesperado")

    with pytest.raises(RuntimeError):
        _servicio(SondaRompe({"10.0.0.14": MAC_PC})).descubrir(interfaz(), threading.Event())
