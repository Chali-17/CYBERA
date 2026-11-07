"""Pruebas del motor real para Windows (WindowsIsolationEngine).

Este motor es HONESTO: se declara no disponible porque, sin control del router o
del conmutador, no hay contención selectiva fiable y recuperable (ver el informe
docs/INFORME_MOTOR_AISLAMIENTO.md). Estas pruebas verifican que cumple el
contrato ``INetworkIsolation`` y que, integrado, la aplicación nunca afirma haber
aislado nada. NO demuestran aislamiento real de la red: no existe tal mecanismo.

El motor SIMULADO (dobles.MotorSimulado) se mantiene para las pruebas unitarias
de la lógica; aquí no se sustituye.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.services.isolation_service import AislamientoNoDisponibleError, IsolationService
from infrastructure.interfaces import (EstadoContencion, ErrorMotorAislamiento, INetworkIsolation,
                                       OperacionNoEjecutadaError)
from infrastructure.network.motor_aislamiento import crear_motor
from infrastructure.network.windows_isolation import WindowsIsolationEngine
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository

T0 = datetime(2026, 10, 21, 9, 0, 0)
MAC = "50:9A:4C:4C:78:B2"
MAC_2 = "AC:00:00:00:00:30"


@pytest.fixture
def motor():
    return WindowsIsolationEngine()


# --- Contrato del motor --------------------------------------------------------

def test_cumple_la_interfaz(motor):
    assert isinstance(motor, INetworkIsolation)


def test_disponible_es_false_sin_efectos_ni_excepciones(motor):
    # Idempotente, rápido, sin lanzar: se puede llamar muchas veces.
    for _ in range(3):
        resultado = motor.disponible()
        assert resultado is False and isinstance(resultado, bool)
    assert isinstance(motor.motivo_no_disponible, str) and motor.motivo_no_disponible


@pytest.mark.parametrize("accion", ["isolate", "release"])
def test_isolate_y_release_no_tocan_la_red(motor, accion):
    # OperacionNoEjecutadaError = el contrato garantiza que NO se modificó la red.
    with pytest.raises(OperacionNoEjecutadaError) as error:
        getattr(motor, accion)(MAC)
    assert isinstance(error.value, ErrorMotorAislamiento)


@pytest.mark.parametrize("mac", [MAC, MAC_2, "no-es-mac", "FF:FF:FF:FF:FF:FF"])
def test_status_siempre_desconocido(motor, mac):
    # Sin evidencia de contención: DESCONOCIDO, nunca SIN_CONTENCION por defecto.
    assert motor.status(mac) is EstadoContencion.DESCONOCIDO


def test_sin_estado_entre_mac(motor):
    # Operar sobre una MAC no cambia el estado de otra (motor sin estado).
    with pytest.raises(OperacionNoEjecutadaError):
        motor.isolate(MAC)
    assert motor.status(MAC_2) is EstadoContencion.DESCONOCIDO
    assert motor.status(MAC) is EstadoContencion.DESCONOCIDO


# --- Fábrica -------------------------------------------------------------------

def test_fabrica_por_defecto_es_el_motor_arp(monkeypatch):
    # El motor real por defecto es el de envenenamiento ARP (aislamiento activo).
    monkeypatch.delenv("CYBERA_MOTOR", raising=False)
    from infrastructure.network.arp_spoofing import ArpSpoofingIsolationEngine
    assert isinstance(crear_motor(), ArpSpoofingIsolationEngine)


def test_fabrica_puede_seleccionar_el_motor_windows_honesto(monkeypatch):
    monkeypatch.setenv("CYBERA_MOTOR", "windows")
    assert isinstance(crear_motor(), WindowsIsolationEngine)


@pytest.mark.parametrize("valor", ["ninguno", "none", "NINGUNO"])
def test_fabrica_puede_desactivar_el_motor(monkeypatch, valor):
    monkeypatch.setenv("CYBERA_MOTOR", valor)
    assert crear_motor() is None


# --- Integración con IsolationService -----------------------------------------

def _servicio(tmp_path, motor):
    repo = JsonIsolationRepository(tmp_path / "aislamientos.json")
    lb = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
    return IsolationService(repo, lb, motor=motor, reloj=lambda: T0), repo


def test_servicio_con_motor_real_informa_no_disponible(tmp_path, motor):
    servicio, repo = _servicio(tmp_path, motor)
    assert servicio.disponible is False            # El motor no está operativo.
    assert servicio._motor is motor                # Pero la dependencia SÍ está conectada.
    with pytest.raises(AislamientoNoDisponibleError):
        servicio.aislar(MAC, "administrador")
    assert servicio.macs_aisladas() == set()
    assert not (tmp_path / "aislamientos.json").exists()   # No se persistió nada.


def test_mensaje_refleja_el_motivo_real_no_falta_de_privilegios(tmp_path, motor):
    # Diagnóstico: el motor está conectado y se declara no disponible a propósito.
    # El mensaje debe explicar el motivo real, no «falta el motor» ni «admin».
    servicio, _ = _servicio(tmp_path, motor)
    with pytest.raises(AislamientoNoDisponibleError) as error:
        servicio.aislar(MAC, "administrador")
    mensaje = str(error.value)
    assert "mecanismo de contención" in mensaje            # Motivo real del motor.
    assert "requiere privilegios de administrador" not in mensaje
    assert "falta el motor" not in mensaje


def test_mensaje_distingue_cuando_no_hay_motor_conectado(tmp_path):
    servicio, _ = _servicio(tmp_path, None)                # motor=None (no conectado).
    with pytest.raises(AislamientoNoDisponibleError) as error:
        servicio.aislar(MAC, "administrador")
    assert "no hay un motor de red de capa 2 conectado" in str(error.value).lower()


def test_servicio_con_motor_real_no_verifica_nada(tmp_path, motor):
    servicio, _ = _servicio(tmp_path, motor)
    # verificar_registrados no hace nada si el motor no está disponible.
    assert servicio.verificar_registrados() == {}


def test_construir_inyecta_el_motor_arp(qapp, tmp_path, monkeypatch):
    # Por defecto, la aplicación inyecta el motor de envenenamiento ARP. Sin
    # administrador no está operativo, así que «Aislar» informa «no disponible»
    # sin tocar la red; ver el motor ARP en tests dedicados.
    monkeypatch.delenv("CYBERA_MOTOR", raising=False)
    from app.main import construir
    from infrastructure.network.arp_spoofing import ArpSpoofingIsolationEngine
    aplicacion = construir(tmp_path)
    try:
        assert isinstance(aplicacion.servicio_aislamiento._motor, ArpSpoofingIsolationEngine)
    finally:
        aplicacion.ejecutor.detener()
        aplicacion.monitoreo.detener()
        aplicacion.configuracion.detener()
