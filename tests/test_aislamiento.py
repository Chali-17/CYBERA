"""Pruebas del aislamiento.

IMPORTANTE: el motor de red real de Capa 2 (INetworkIsolation) NO está
implementado. Estas pruebas usan un MOTOR DOBLE para verificar la LÓGICA de
IsolationService (validaciones, verificación por status, persistencia). No
demuestran que el aislamiento real de la red funcione; no existe ninguna prueba
de integración con un mecanismo de aislamiento real porque ese motor falta.
"""

import json
from datetime import datetime

import pytest

from app.models.aislamiento import AccionAislamiento, EstadoAislamiento
from app.models.dispositivo_confiable import DispositivoConfiable, OrigenRegistro
from app.services.isolation_service import (AislamientoError, AislamientoFallidoError,
                                            AislamientoNoDisponibleError, DispositivoProtegidoError,
                                            IsolationService)
from infrastructure.interfaces import EstadoRed, INetworkIsolation
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository

T0 = datetime(2026, 10, 20, 12, 0, 0)
MAC = "50:9A:4C:4C:78:B2"


class MotorDoble(INetworkIsolation):
    """Motor de aislamiento SIMULADO para probar la lógica del servicio."""

    def __init__(self, confirma=True, falla_isolate=False):
        self.confirma = confirma
        self.falla_isolate = falla_isolate
        self.aisladas: set[str] = set()
        self.llamadas: list[str] = []

    def isolate(self, mac):
        self.llamadas.append(mac)
        if self.falla_isolate:
            raise OSError("se requieren privilegios de administrador")
        if self.confirma:
            self.aisladas.add(mac)

    def release(self, mac):
        self.aisladas.discard(mac)

    def status(self, mac):
        return EstadoRed.AISLADO if mac in self.aisladas else EstadoRed.ACTIVO


def _servicio(tmp_path, motor=None):
    repo = JsonIsolationRepository(tmp_path / "aislamientos.json")
    lb = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
    return IsolationService(repo, lb, motor=motor, reloj=lambda: T0), repo, lb


# --- Repositorio --------------------------------------------------------------

def test_repositorio_crea_y_finaliza(tmp_path):
    repo = JsonIsolationRepository(tmp_path / "aislamientos.json")
    repo.crear(AccionAislamiento(mac_objetivo=MAC, fecha_inicio=T0, autorizado_por="u"))
    assert repo.macs_activas() == {MAC}
    datos = json.loads((tmp_path / "aislamientos.json").read_text(encoding="utf-8"))
    assert datos["aislamientos"][0]["estado"] == "ACTIVO"
    repo.finalizar(MAC, T0)
    assert repo.macs_activas() == set()
    assert JsonIsolationRepository(tmp_path / "aislamientos.json").activos() == []


def test_repositorio_rechaza_doble_aislamiento_activo(tmp_path):
    repo = JsonIsolationRepository(tmp_path / "aislamientos.json")
    repo.crear(AccionAislamiento(mac_objetivo=MAC, fecha_inicio=T0, autorizado_por="u"))
    with pytest.raises(ValueError):
        repo.crear(AccionAislamiento(mac_objetivo=MAC, fecha_inicio=T0, autorizado_por="u"))


def test_accion_ida_y_vuelta():
    a = AccionAislamiento(mac_objetivo=MAC, fecha_inicio=T0, autorizado_por="u",
                          estado=EstadoAislamiento.INACTIVO, fecha_fin=T0)
    assert AccionAislamiento.desde_dict(a.a_dict()) == a


# --- Servicio (con motor doble) ----------------------------------------------

def test_sin_motor_no_disponible_y_no_persiste(tmp_path):
    servicio, repo, _ = _servicio(tmp_path, motor=None)
    assert not servicio.disponible
    with pytest.raises(AislamientoNoDisponibleError):
        servicio.aislar(MAC, "u")
    assert repo.macs_activas() == set()
    assert not (tmp_path / "aislamientos.json").exists()


def test_no_aisla_dispositivo_en_lista_blanca(tmp_path):
    motor = MotorDoble()
    servicio, repo, lb = _servicio(tmp_path, motor=motor)
    lb.add(DispositivoConfiable(MAC, "PC", T0, OrigenRegistro.ESCANEO, True))
    with pytest.raises(DispositivoProtegidoError):     # RI-05
        servicio.aislar(MAC, "u")
    assert motor.llamadas == [] and repo.macs_activas() == set()


@pytest.mark.parametrize("mac", ["no-es-mac", "FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"])
def test_no_aisla_mac_invalida(tmp_path, mac):
    servicio, repo, _ = _servicio(tmp_path, motor=MotorDoble())
    with pytest.raises(AislamientoError):
        servicio.aislar(mac, "u")
    assert repo.macs_activas() == set()


def test_motor_no_confirma_no_persiste(tmp_path):
    motor = MotorDoble(confirma=False)
    servicio, repo, _ = _servicio(tmp_path, motor=motor)
    with pytest.raises(AislamientoFallidoError):
        servicio.aislar(MAC, "u")
    assert repo.macs_activas() == set()


def test_motor_falla_no_persiste(tmp_path):
    motor = MotorDoble(falla_isolate=True)
    servicio, repo, _ = _servicio(tmp_path, motor=motor)
    with pytest.raises(OSError):
        servicio.aislar(MAC, "u")
    assert repo.macs_activas() == set()


def test_aislamiento_confirmado_persiste(tmp_path):
    motor = MotorDoble(confirma=True)
    servicio, repo, _ = _servicio(tmp_path, motor=motor)
    accion = servicio.aislar(MAC, "administrador")
    assert accion.mac_objetivo == MAC and accion.activo
    assert repo.macs_activas() == {MAC}
    assert servicio.macs_aisladas() == {MAC}
