"""Pruebas de regresión del cierre de limitaciones previas al motor real (L1–L5).

Usan un MOTOR SIMULADO o ningún motor. No demuestran que una red real quede
aislada: verifican la lógica de `IsolationService`, no el envenenamiento ARP real
(eso lo cubre tests/test_motor_arp.py con dobles).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QPushButton

from app.controllers.ejecutor_aislamiento import AISLAR, DESBLOQUEAR, EjecutorAislamiento
from app.controllers.isolation_controller import IsolationController
from app.models.dispositivo_confiable import DispositivoConfiable, OrigenRegistro
from app.models.operacion_aislamiento import (EstadoOperacion, MotivoFallo, OperacionAislamiento,
                                              TipoOperacion)
from app.services.device_discovery_service import DeviceDiscoveryService
from app.services.isolation_service import (AislamientoFallidoError, AislamientoNoDisponibleError,
                                            DesbloqueoFallidoError, DispositivoProtegidoError,
                                            IsolationService, OperacionEnCursoError,
                                            TransicionNoPermitidaError)
from app.services.monitoring_service import MonitoringService
from app.services.network_interface_service import NetworkInterfaceService
from app.services.reservas_mac import coordinador_para
from app.services.settings_service import SettingsService
from app.services.whitelist_service import AutorizacionBloqueadaError, WhitelistService
from dobles import (HostnamesFalso, MotorSimulado, OuiFalso, ProveedorInterfacesFalso, SondaFalsa,
                    interfaz)
from infrastructure.compatibilidad_datos import problema_carpeta_datos
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.persistence.json_file import ArchivoDatosError
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository
from presentation.views.isolation_view import SIN_DISPOSITIVOS, IsolationView

RAIZ = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 21, 9, 0, 0)
MAC = "50:9A:4C:4C:78:B2"
MAC_2 = "AC:00:00:00:00:30"
ACTOR = "administrador local"


def servicio(carpeta: Path, motor=None) -> IsolationService:
    """IsolationService «de producción»: sin reservas explícitas."""
    return IsolationService(JsonIsolationRepository(carpeta / "aislamientos.json"),
                            JsonWhitelistRepository(carpeta / "lista_blanca.json"),
                            motor=motor, reloj=lambda: T0)


def estados(carpeta: Path, mac=MAC):
    repo = JsonIsolationRepository(carpeta / "aislamientos.json")
    return [(o.tipo.value, o.estado.value, o.motivo_fallo.value if o.motivo_fallo else None)
            for o in repo.operaciones(mac)]


def _en_hilo(funcion, *args):
    resultado = {}

    def ejecutar():
        try:
            resultado["valor"] = funcion(*args)
        except BaseException as error:  # noqa: BLE001
            resultado["error"] = error

    hilo = threading.Thread(target=ejecutar, daemon=True)
    hilo.start()
    return hilo, resultado


def esperar(qapp, condicion, limite=10.0):
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        qapp.processEvents()
        if condicion():
            return True
        time.sleep(0.01)
    return False


# =============================================================================
# L1 — Coordinación por MAC en todo el proceso
# =============================================================================

def test_l1_dos_isolation_service_sobre_el_mismo_repositorio_se_coordinan(tmp_path):
    motor = MotorSimulado()
    repo = JsonIsolationRepository(tmp_path / "aislamientos.json")
    lb = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
    uno = IsolationService(repo, lb, motor=motor, reloj=lambda: T0)
    dos = IsolationService(repo, lb, motor=motor, reloj=lambda: T0)
    liberar = motor.bloquear(MAC)
    hilo, resultado = _en_hilo(uno.aislar, MAC, ACTOR)
    assert motor.dentro[MAC].wait(5)
    with pytest.raises(OperacionEnCursoError):
        dos.aislar(MAC, ACTOR)                         # Duplicado desde otra instancia
    with pytest.raises(OperacionEnCursoError):
        dos.desbloquear(MAC, ACTOR)                    # Incompatible desde otra instancia
    liberar.set()
    hilo.join(5)
    assert "error" not in resultado
    assert motor.llamadas == [("isolate", MAC)]        # Una sola orden al motor
    assert estados(tmp_path) == [("AISLAR", "CONFIRMED", None)]


def test_l1_repositorios_distintos_sobre_el_mismo_archivo_se_coordinan(tmp_path):
    motor = MotorSimulado()
    uno, dos = servicio(tmp_path, motor), servicio(tmp_path, motor)
    assert uno._reservas is dos._reservas is coordinador_para(tmp_path)
    assert uno._repo._archivo.lock is dos._repo._archivo.lock   # Candado de archivo único
    liberar = motor.bloquear(MAC)
    hilo, _ = _en_hilo(uno.aislar, MAC, ACTOR)
    assert motor.dentro[MAC].wait(5)
    with pytest.raises(OperacionEnCursoError):
        dos.aislar(MAC, ACTOR)
    liberar.set()
    hilo.join(5)
    assert motor.llamadas == [("isolate", MAC)]


def test_l1_lista_blanca_por_defecto_comparte_el_coordinador(tmp_path):
    motor = MotorSimulado()
    aislamiento = servicio(tmp_path, motor)
    lista = WhitelistService(JsonWhitelistRepository(tmp_path / "lista_blanca.json"))
    liberar = motor.bloquear(MAC)
    hilo, _ = _en_hilo(aislamiento.aislar, MAC, ACTOR)
    assert motor.dentro[MAC].wait(5)
    with pytest.raises(AutorizacionBloqueadaError):
        lista.autorizar(MAC, "PC")
    liberar.set()
    hilo.join(5)


def test_l1_carpetas_distintas_y_mac_distintas_son_independientes(tmp_path):
    motor = MotorSimulado()
    a, b = servicio(tmp_path / "a", motor), servicio(tmp_path / "b", motor)
    assert a._reservas is not b._reservas
    liberar = motor.bloquear(MAC)
    hilo, _ = _en_hilo(a.aislar, MAC, ACTOR)
    assert motor.dentro[MAC].wait(5)
    a.aislar(MAC_2, ACTOR)                             # Otra MAC, mismo servicio: avanza
    liberar.set()
    hilo.join(5)
    assert a.macs_aisladas() == {MAC, MAC_2}


def test_l1_construir_usa_el_coordinador_de_la_carpeta(qapp, tmp_path):
    from app.main import construir
    aplicacion = construir(tmp_path)
    try:
        compartido = coordinador_para(tmp_path)
        assert aplicacion.servicio_aislamiento._reservas is compartido
        assert aplicacion.servicio_lista_blanca._reservas is compartido
        assert servicio(tmp_path)._reservas is compartido     # Cualquier otro servicio también
    finally:
        aplicacion.ejecutor.detener()
        aplicacion.monitoreo.detener()
        aplicacion.configuracion.detener()


# =============================================================================
# L2 — Estado explícito UNCERTAIN y recuperación
# =============================================================================

def _autorizar_por_fuera(carpeta: Path, mac=MAC):
    JsonWhitelistRepository(carpeta / "lista_blanca.json").add(
        DispositivoConfiable(mac, "PC", T0, OrigenRegistro.MANUAL, True))


def test_l2_reversion_fallida_y_recuperacion_explicita(tmp_path, monkeypatch):
    motor = MotorSimulado()
    s = servicio(tmp_path, motor)
    original = motor.isolate

    def isolate(mac):
        original(mac)
        _autorizar_por_fuera(tmp_path)
        motor.falla_release = True

    monkeypatch.setattr(motor, "isolate", isolate)
    with pytest.raises(DispositivoProtegidoError):
        s.aislar(MAC, ACTOR)
    assert estados(tmp_path) == [("AISLAR", "UNCERTAIN", "REVERSION_FALLIDA")]
    llamadas = list(motor.llamadas)
    # Nada se reintenta solo: ni al consultar, ni al verificar, ni al recuperar.
    s.situaciones()
    s.verificar_registrados()
    s.recuperar_interrumpidas()
    assert motor.llamadas == llamadas
    # Recuperación explícita: desbloqueo sin contención registrada.
    motor.falla_release = False
    assert s.desbloquear(MAC, ACTOR) is None
    assert not s.requiere_recuperacion(MAC)
    ops = JsonIsolationRepository(tmp_path / "aislamientos.json").operaciones(MAC)
    assert [o.estado.value for o in ops] == ["UNCERTAIN", "CONFIRMED"]
    assert ops[0].id_recuperacion == ops[1].id_operacion          # Evidencia enlazada
    assert ops[1].id_aislamiento is None                         # Desbloqueo de recuperación
    assert JsonWhitelistRepository(tmp_path / "lista_blanca.json").exists(MAC)  # Intacta


def test_l2_recuperacion_fallida_sigue_pendiente(tmp_path):
    motor = MotorSimulado(falla_isolate=True)
    s = servicio(tmp_path, motor)
    with pytest.raises(AislamientoFallidoError):
        s.aislar(MAC, ACTOR)
    motor.falla_release = True
    with pytest.raises(DesbloqueoFallidoError) as error:
        s.desbloquear(MAC, ACTOR)
    assert error.value.requiere_recuperacion
    assert s.requiere_recuperacion(MAC)
    assert [e[1] for e in estados(tmp_path)] == ["UNCERTAIN", "UNCERTAIN"]


def test_l2_recuperacion_tras_reinicio_segun_el_motor(tmp_path):
    # Aislamiento interrumpido: queda REQUESTED en disco.
    repo = JsonIsolationRepository(tmp_path / "aislamientos.json")
    repo.registrar_solicitud(OperacionAislamiento(MAC, TipoOperacion.AISLAR, ACTOR, T0).solicitar())
    # Motor conservador (no puede restaurar lo que no conoce): no se verifica.
    conservador = servicio(tmp_path, MotorSimulado())
    conservador.recuperar_interrumpidas()
    with pytest.raises(DesbloqueoFallidoError, match="DESCONOCIDO"):
        conservador.desbloquear(MAC, ACTOR)
    assert conservador.requiere_recuperacion(MAC)
    # Motor restaurador (cumple el contrato de release): se verifica y se resuelve.
    restaurador = servicio(tmp_path, MotorSimulado(restaura_desconocidas=True))
    restaurador.desbloquear(MAC, ACTOR)
    assert not restaurador.requiere_recuperacion(MAC)


def test_l2_operacion_no_ejecutada_es_fallo_conocido(tmp_path):
    s = servicio(tmp_path, MotorSimulado(no_ejecuta=True))
    with pytest.raises(AislamientoFallidoError) as error:
        s.aislar(MAC, ACTOR)
    assert not error.value.requiere_recuperacion
    assert estados(tmp_path) == [("AISLAR", "FAILED", "ERROR_MOTOR")]
    assert not s.requiere_recuperacion(MAC)


def test_l2_desbloqueo_sin_registro_ni_recuperacion_se_rechaza(tmp_path):
    s = servicio(tmp_path, MotorSimulado(confirma_aislar=False))
    with pytest.raises(AislamientoFallidoError):
        s.aislar(MAC, ACTOR)                           # FAILED conocido: no requiere recuperación
    with pytest.raises(TransicionNoPermitidaError):
        s.desbloquear(MAC, ACTOR)


def test_l2_desbloqueo_de_recuperacion_sin_motor_no_cambia_nada(tmp_path):
    with pytest.raises(AislamientoFallidoError):
        servicio(tmp_path, MotorSimulado(falla_isolate=True)).aislar(MAC, ACTOR)
    s = servicio(tmp_path, None)
    with pytest.raises(AislamientoNoDisponibleError):
        s.desbloquear(MAC, ACTOR)
    assert s.requiere_recuperacion(MAC)


def test_l2_failed_interrumpida_antiguo_se_trata_como_incierto(tmp_path):
    op = OperacionAislamiento(MAC, TipoOperacion.AISLAR, ACTOR, T0).solicitar().a_dict()
    op.update(estado="FAILED", motivoFallo="INTERRUMPIDA", fechaResolucion=T0.isoformat())
    (tmp_path / "aislamientos.json").write_text(
        json.dumps({"version": 2, "aislamientos": [], "operaciones": [op]}), encoding="utf-8")
    assert servicio(tmp_path).requiere_recuperacion(MAC)


@pytest.mark.parametrize("cambio", [
    {"idRecuperacion": "no-existe"},
    {"estado": "CONFIRMED", "motivoFallo": None, "idRecuperacion": "x"},
])
def test_l2_id_recuperacion_incoherente_se_rechaza(tmp_path, cambio):
    op = OperacionAislamiento(MAC, TipoOperacion.AISLAR, ACTOR, T0).solicitar().marcar_incierta(
        MotivoFallo.ERROR_MOTOR, T0).a_dict()
    op.update(cambio)
    contenido = json.dumps({"version": 2, "aislamientos": [], "operaciones": [op]})
    ruta = tmp_path / "aislamientos.json"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(ArchivoDatosError):
        JsonIsolationRepository(ruta).operaciones()
    assert ruta.read_text(encoding="utf-8") == contenido


def test_l2_repositorio_rechaza_recuperacion_sin_pendiente(tmp_path):
    repo = JsonIsolationRepository(tmp_path / "aislamientos.json")
    with pytest.raises(ValueError, match="recuperación"):
        repo.registrar_solicitud(
            OperacionAislamiento(MAC, TipoOperacion.DESBLOQUEAR, ACTOR, T0).solicitar())


# =============================================================================
# L3 — Pantalla Aislamiento (Mockup 06)
# =============================================================================

class Pantalla:
    def __init__(self, carpeta: Path, motor=None, ejecutor_asincrono=False):
        self.carpeta = carpeta
        self.motor = motor
        self.servicio = servicio(carpeta, motor)
        self.lb = WhitelistService(JsonWhitelistRepository(carpeta / "lista_blanca.json"))
        cfg = SettingsService(JsonSettingsRepository(carpeta / "configuracion.json"))
        descubrimiento = DeviceDiscoveryService(SondaFalsa(), OuiFalso(), HostnamesFalso(),
                                                tiempo_maximo_hostname=0.1)
        self.monitoreo = MonitoringService(cfg, NetworkInterfaceService(
            ProveedorInterfacesFalso([interfaz()])), descubrimiento, self.lb,
            aislamiento=self.servicio)
        self.ejecutor = EjecutorAislamiento(self.servicio, asincrono=ejecutor_asincrono)
        self.vista = IsolationView()
        self.ctrl = IsolationController(self.vista, self.servicio, self.lb, self.monitoreo,
                                        ejecutor=self.ejecutor)
        self.avisos, self.informes = [], []
        self.vista.advertir = lambda t, m: self.avisos.append((t, m))
        self.vista.informar = lambda t, m: self.informes.append((t, m))
        self.vista.confirmar_desbloqueo = lambda *a: True

    def filas(self):
        return {f.mac: f for f in self.vista.filas()}


def test_l3_estructura_del_mockup_06(qapp, tmp_path):
    p = Pantalla(tmp_path)
    p.ctrl.recargar()
    from PySide6.QtWidgets import QLabel
    textos = {e.text() for e in p.vista.findChildren(QLabel)}
    assert {"Aislamiento", "Gestión de dispositivos bajo contención",
            "Dispositivos aislados"} <= textos
    assert not any("Mockup" in t for t in textos)          # Sin leyenda de pie
    assert SIN_DISPOSITIVOS in textos
    assert p.vista.findChildren(QPushButton) == []     # Sin controles fuera del mockup


def test_l3_tarjetas_distinguen_estados_sin_verificar(qapp, tmp_path):
    motor = MotorSimulado()
    servicio(tmp_path, motor).aislar(MAC, ACTOR)        # Registrado (otra «ejecución»)
    with pytest.raises(AislamientoFallidoError):        # MAC_2: resultado incierto
        servicio(tmp_path, MotorSimulado(falla_isolate=True)).aislar(MAC_2, ACTOR)
    p = Pantalla(tmp_path, None)                        # Sin motor: nada verificado
    p.ctrl.recargar()
    filas = p.filas()
    assert (filas[MAC].insignia, filas[MAC].tono) == ("Sin verificar", "ambar")
    assert filas[MAC].ayuda == "Registrado, estado sin verificar"
    assert (filas[MAC_2].insignia, filas[MAC_2].tono) == ("Requiere recuperación", "ambar")
    assert filas[MAC].nombre == "Desconocido" and filas[MAC].ip == "No disponible"
    assert filas[MAC].fecha == "21/10/2026 09:00"
    assert all(f.puede_desbloquear for f in filas.values())
    # Cada tarjeta tiene el botón «Desbloquear» (como el mockup). La de
    # «Requiere recuperación» además tiene la acción manual «Quitar de la lista».
    botones = p.vista.findChildren(QPushButton)
    assert len(botones) == 3 and {b.text() for b in botones} == {"Desbloquear", "Quitar de la lista"}
    assert p.vista.boton_quitar(MAC) is None
    assert p.vista.boton_quitar(MAC_2) is not None


def test_l3_aislado_solo_cuando_el_motor_lo_verifico(qapp, tmp_path):
    p = Pantalla(tmp_path, MotorSimulado())
    p.servicio.aislar(MAC, ACTOR)                       # Verificado en esta ejecución
    p.ctrl.recargar()
    fila = p.filas()[MAC]
    assert (fila.insignia, fila.tono) == ("Aislado", "rojo")
    assert fila.ayuda.startswith("Contención aplicada según el motor (verificado")


def test_l3_desbloquear_desde_la_pantalla(qapp, tmp_path):
    p = Pantalla(tmp_path, MotorSimulado())
    p.servicio.aislar(MAC, ACTOR)
    p.ctrl.recargar()
    p.vista.boton_desbloquear(MAC).click()
    assert p.informes and p.informes[0][0] == "Contención retirada"
    assert "no comprueba por sí solo" in p.informes[0][1]
    assert MAC not in p.filas()                          # Ya no figura bajo contención
    assert p.servicio.macs_aisladas() == set()


def test_l3_cancelar_confirmacion_no_hace_nada(qapp, tmp_path):
    p = Pantalla(tmp_path, MotorSimulado())
    p.servicio.aislar(MAC, ACTOR)
    p.ctrl.recargar()
    p.vista.confirmar_desbloqueo = lambda *a: False
    p.vista.boton_desbloquear(MAC).click()
    assert p.motor.llamadas == [("isolate", MAC)] and p.servicio.macs_aisladas() == {MAC}


@pytest.mark.parametrize("cambios, titulo, insignia", [
    ({"falla_release": True}, "Resultado incierto: requiere recuperación", "Requiere recuperación"),
    ({"confirma_liberar": False}, "Desbloqueo fallido", "Aislado"),
    ({"no_ejecuta": True}, "Desbloqueo fallido", "Aislado"),
])
def test_l3_desbloqueo_fallido_se_muestra_sin_falsos_estados(qapp, tmp_path, cambios, titulo,
                                                            insignia):
    p = Pantalla(tmp_path, MotorSimulado())
    p.servicio.aislar(MAC, ACTOR)
    for clave, valor in cambios.items():
        setattr(p.motor, clave, valor)
    p.ctrl.recargar()
    p.vista.boton_desbloquear(MAC).click()
    assert p.avisos and p.avisos[0][0] == titulo and not p.informes
    assert p.filas()[MAC].insignia == insignia          # Sigue listado, sin «desbloqueado»
    assert p.servicio.macs_aisladas() == {MAC}


def test_l3_desbloqueo_sin_motor_informa_no_disponible(qapp, tmp_path):
    servicio(tmp_path, MotorSimulado()).aislar(MAC, ACTOR)
    p = Pantalla(tmp_path, None)
    p.ctrl.recargar()
    p.vista.boton_desbloquear(MAC).click()
    assert p.avisos[0][0] == "Desbloqueo no disponible"
    assert p.filas()[MAC].insignia == "Sin verificar"


def test_l3_boton_quitar_solo_en_situacion_requiere_recuperacion(qapp, tmp_path):
    p = Pantalla(tmp_path, MotorSimulado(falla_isolate=True))   # MAC_2 queda en «Requiere recuperación»
    with pytest.raises(AislamientoFallidoError):
        p.servicio.aislar(MAC_2, ACTOR)
    p.ctrl.recargar()
    filas = p.filas()
    assert filas[MAC_2].insignia == "Requiere recuperación"
    assert filas[MAC_2].puede_quitar is True          # Sólo para recuperación bloqueada
    assert p.vista.boton_quitar(MAC_2) is not None
    assert p.vista.boton_desbloquear(MAC_2) is not None


def test_l3_quitar_de_la_lista_saca_dispositivo_del_listado(qapp, tmp_path):
    p = Pantalla(tmp_path, MotorSimulado(falla_isolate=True))
    with pytest.raises(AislamientoFallidoError):
        p.servicio.aislar(MAC_2, ACTOR)
    p.ctrl.recargar()
    assert MAC_2 in p.filas()
    p.vista.confirmar_quitar = lambda *a: True
    p.vista.boton_quitar(MAC_2).click()               # Emite quitarSolicitado -> _quitar
    assert MAC_2 not in p.filas()
    assert p.servicio.macs_aisladas() == set()


def test_l3_cancelar_quitar_no_hace_nada(qapp, tmp_path):
    p = Pantalla(tmp_path, MotorSimulado(falla_isolate=True))
    with pytest.raises(AislamientoFallidoError):
        p.servicio.aislar(MAC_2, ACTOR)
    p.ctrl.recargar()
    p.vista.confirmar_quitar = lambda *a: False
    p.vista.boton_quitar(MAC_2).click()
    assert MAC_2 in p.filas()


def test_l3_alias_de_lista_blanca_y_archivo_danado(qapp, tmp_path):
    servicio(tmp_path, MotorSimulado()).aislar(MAC, ACTOR)
    p = Pantalla(tmp_path, None)
    p.lb.autorizar(MAC, "Equipo temporal")              # Autorizado después (independiente)
    p.ctrl.recargar()
    assert p.filas()[MAC].nombre == "Equipo temporal"
    (tmp_path / "aislamientos.json").write_text("dañado", encoding="utf-8")
    p.ctrl.recargar()
    assert p.vista.filas() == []


def test_l3_la_aplicacion_muestra_la_pantalla_aislamiento(qapp, tmp_path):
    from app.main import construir
    aplicacion = construir(tmp_path)
    try:
        assert "Aislamiento" in aplicacion.ventana.botones
        aplicacion.ventana.ir_a("Aislamiento")
        assert isinstance(aplicacion.aislamiento, IsolationController)
    finally:
        aplicacion.ejecutor.detener()
        aplicacion.monitoreo.detener()
        aplicacion.configuracion.detener()


# =============================================================================
# L4 — Trabajo en segundo plano
# =============================================================================

def test_l4_la_operacion_no_bloquea_el_hilo_de_la_interfaz(qapp, tmp_path):
    motor = MotorSimulado()
    ejecutor = EjecutorAislamiento(servicio(tmp_path, motor), asincrono=True)
    hilos, terminadas = [], []
    ejecutor.terminada.connect(lambda mac, tipo, ctx, r: (terminadas.append((mac, tipo)),
                                                          hilos.append(QThread.currentThread())))
    liberar = motor.bloquear(MAC)
    inicio = time.monotonic()
    assert ejecutor.solicitar(AISLAR, MAC, ACTOR)
    assert time.monotonic() - inicio < 0.5             # Regresa sin esperar al motor
    assert motor.dentro[MAC].wait(5)
    assert ejecutor.en_curso(MAC)
    assert not ejecutor.solicitar(AISLAR, MAC, ACTOR)   # Duplicado rechazado
    assert not ejecutor.solicitar(DESBLOQUEAR, MAC, ACTOR)
    liberar.set()
    assert esperar(qapp, lambda: terminadas)
    assert terminadas == [(MAC, AISLAR)]
    assert hilos == [qapp.thread()]                     # Resultado en el hilo de la GUI
    assert not ejecutor.en_curso(MAC)
    ejecutor.detener()


def test_l4_los_errores_llegan_con_su_tipo(qapp, tmp_path):
    ejecutor = EjecutorAislamiento(servicio(tmp_path, None), asincrono=True)
    errores = []
    ejecutor.fallida.connect(lambda mac, tipo, ctx, error: errores.append((ctx, error)))
    assert ejecutor.solicitar(AISLAR, MAC, ACTOR, contexto="origen")
    assert esperar(qapp, lambda: errores)
    assert errores[0][0] == "origen"
    assert isinstance(errores[0][1], AislamientoNoDisponibleError)
    ejecutor.detener()


def test_l4_cancelacion_solo_antes_de_empezar(qapp, tmp_path):
    motor = MotorSimulado()
    ejecutor = EjecutorAislamiento(servicio(tmp_path, motor), asincrono=True, max_hilos=1)
    canceladas, terminadas = [], []
    ejecutor.cancelada.connect(lambda mac, tipo, ctx: canceladas.append(mac))
    ejecutor.terminada.connect(lambda mac, tipo, ctx, r: terminadas.append(mac))
    liberar = motor.bloquear(MAC)
    assert ejecutor.solicitar(AISLAR, MAC, ACTOR)
    assert motor.dentro[MAC].wait(5)
    assert ejecutor.solicitar(AISLAR, MAC_2, ACTOR)     # En cola: el único hilo está ocupado
    assert not ejecutor.cancelar(MAC)                   # En ejecución: no es seguro cancelar
    assert ejecutor.cancelar(MAC_2)                     # En cola: se retira
    assert canceladas == [MAC_2] and not ejecutor.en_curso(MAC_2)
    liberar.set()
    assert esperar(qapp, lambda: terminadas)
    assert ("isolate", MAC_2) not in motor.llamadas     # Nunca llegó al motor
    assert estados(tmp_path, MAC_2) == []
    ejecutor.detener()


def test_l4_detener_espera_y_no_acepta_nuevas(qapp, tmp_path):
    motor = MotorSimulado()
    ejecutor = EjecutorAislamiento(servicio(tmp_path, motor), asincrono=True)
    liberar = motor.bloquear(MAC)
    assert ejecutor.solicitar(AISLAR, MAC, ACTOR)
    assert motor.dentro[MAC].wait(5)
    threading.Timer(0.3, liberar.set).start()
    assert ejecutor.detener(espera_ms=10000)            # Aguardó a la operación en curso
    assert estados(tmp_path) == [("AISLAR", "CONFIRMED", None)]
    assert not ejecutor.solicitar(AISLAR, MAC_2, ACTOR)


def test_l4_controlador_de_dispositivos_asincrono(qapp, tmp_path, monkeypatch):
    from test_controladores_gui import MAC_PC, App, _macs_en_tabla
    from presentation.views.review_dialog import ACCION_AISLAR
    motor = MotorSimulado()
    a = App(tmp_path, motor=motor)
    try:
        ejecutor = EjecutorAislamiento(a.aislamiento, asincrono=True)
        from app.controllers.device_controller import DeviceController
        a.dispositivos = DeviceController(a.vista_disp, a.monitoreo, a.servicio, a.lb,
                                          a.aislamiento, ejecutor=ejecutor)
        a.cfg.seleccionar_interfaz(interfaz())
        a.cfg.activar_monitoreo()
        a.monitoreo.iniciar()
        assert esperar(qapp, lambda: MAC_PC in _macs_en_tabla(a.vista_disp))
        monkeypatch.setattr(a.vista_disp, "solicitar_decision", lambda perfil: (ACCION_AISLAR, None))
        monkeypatch.setattr(a.vista_disp, "confirmar_aislamiento", lambda perfil: True)
        informes = []
        monkeypatch.setattr(a.vista_disp, "informar", lambda t, m: informes.append(t))
        liberar = motor.bloquear(MAC_PC)
        a.vista_disp.revisarSolicitado.emit(MAC_PC)      # Regresa sin esperar al motor
        assert motor.dentro[MAC_PC].wait(5)
        assert informes == [] and MAC_PC in _macs_en_tabla(a.vista_disp)
        liberar.set()
        assert esperar(qapp, lambda: informes == ["Contención confirmada"])
        assert esperar(qapp, lambda: MAC_PC not in _macs_en_tabla(a.vista_disp))
        ejecutor.detener()
    finally:
        a.cerrar()


def test_l4_construir_usa_un_ejecutor_asincrono_compartido(qapp, tmp_path):
    from app.main import construir
    aplicacion = construir(tmp_path)
    try:
        ejecutor = aplicacion.ejecutor
        assert ejecutor.asincrono
        assert aplicacion.dispositivos._ejecutor is ejecutor
        assert aplicacion.lista_blanca._ejecutor is ejecutor
        assert aplicacion.aislamiento._ejecutor is ejecutor
    finally:
        aplicacion.ejecutor.detener()
        aplicacion.monitoreo.detener()
        aplicacion.configuracion.detener()


# =============================================================================
# L5 — Compatibilidad con versiones anteriores
# =============================================================================

@pytest.mark.parametrize("nombre", ["ControlAislamiento", "controlaislamiento"])
def test_l5_carpeta_heredada_se_rechaza(tmp_path, nombre):
    assert "versiones anteriores" in problema_carpeta_datos(tmp_path / nombre)


@pytest.mark.parametrize("archivo", ["dispositivos.json", "alertas.json", "notificaciones.json",
                                     "bitacora.jsonl"])
def test_l5_archivos_heredados_se_rechazan(tmp_path, archivo):
    (tmp_path / archivo).write_text("{}", encoding="utf-8")
    assert archivo in problema_carpeta_datos(tmp_path)


def test_l5_notificaciones_de_cybera_no_es_heredado(tmp_path):
    # El módulo de correo de CYBERA crea su propio notificaciones.json: no debe
    # impedir que la aplicación arranque.
    (tmp_path / "notificaciones.json").write_text(
        '{"version": 1, "remitente": "cuenta@gmail.com"}', encoding="utf-8")
    assert problema_carpeta_datos(tmp_path) is None


def test_l5_carpeta_propia_es_valida(tmp_path):
    (tmp_path / "aislamientos.json").write_text('{"version": 2, "aislamientos": []}',
                                                encoding="utf-8")
    assert problema_carpeta_datos(tmp_path) is None


@pytest.mark.parametrize("caso", ["nombre", "archivos"])
def test_l5_main_no_arranca_ni_toca_una_carpeta_heredada(tmp_path, caso):
    carpeta = tmp_path / ("ControlAislamiento" if caso == "nombre" else "datos")
    carpeta.mkdir()
    (carpeta / "aislamientos.json").write_text('{"formato": "antiguo"}', encoding="utf-8")
    if caso == "archivos":
        (carpeta / "alertas.json").write_text("[]", encoding="utf-8")
    previo = {p.name: p.read_bytes() for p in carpeta.iterdir()}
    codigo = textwrap.dedent("""
        import sys; sys.path.insert(0, "src")
        import app.main as m
        avisos = []
        class Caja:
            information = staticmethod(lambda *a: avisos.append("info"))
            critical = staticmethod(lambda *a: avisos.append("critico"))
        m.QMessageBox = Caja
        def no_construir(*a, **k):
            raise AssertionError("construir() no debe llamarse")
        m.construir = no_construir
        print(m.main(), avisos[0], flush=True)
    """)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "CYBERA_DATOS": str(carpeta)}
    proceso = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=env,
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proceso.stdout.split() == ["1", "critico"], proceso.stderr
    assert {p.name: p.read_bytes() for p in carpeta.iterdir()} == previo   # Ni bloqueo ni cambios
