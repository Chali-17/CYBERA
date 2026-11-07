"""Pruebas de la máquina de estados del aislamiento (Pending/Requested/Confirmed/Failed).

IMPORTANTE: todas usan un MOTOR SIMULADO (``dobles.MotorSimulado``). Verifican la
LÓGICA de IsolationService, la exclusión mutua por MAC y la persistencia en
aislamientos.json. NO demuestran que el aislamiento real de la red funcione: el
motor de red de Capa 2 no está implementado en esta fase.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime

import pytest

from app.models.aislamiento import AccionAislamiento
from app.models.dispositivo_confiable import DispositivoConfiable, OrigenRegistro
from app.models.operacion_aislamiento import (TRANSICIONES, EstadoOperacion, MotivoFallo,
                                              OperacionAislamiento, TipoOperacion,
                                              TransicionInvalidaError)
from app.services.device_discovery_service import DeviceDiscoveryService
from app.services.isolation_service import (AislamientoError, AislamientoFallidoError,
                                            AislamientoNoDisponibleError, DesbloqueoFallidoError,
                                            DispositivoProtegidoError, IsolationService,
                                            OperacionEnCursoError, RegistroAislamientoError,
                                            TransicionNoPermitidaError)
from app.services.monitoring_service import MonitoringService, TipoResultado
from app.services.network_interface_service import NetworkInterfaceService
from app.services.settings_service import SettingsService
from app.services.whitelist_service import WhitelistService
from dobles import (HostnamesFalso, MotorSimulado, OuiFalso, ProveedorInterfacesFalso,
                    SondaFalsa, interfaz)
from infrastructure.interfaces import EstadoContencion
from infrastructure.persistence import json_file
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository
from presentation import formato

T0 = datetime(2026, 10, 21, 9, 0, 0)
MAC = "50:9A:4C:4C:78:B2"
MAC_2 = "AC:00:00:00:00:30"
ACTOR = "administrador local"


class Entorno:
    def __init__(self, tmp_path, motor=None):
        self.ruta = tmp_path / "aislamientos.json"
        self.repo = JsonIsolationRepository(self.ruta)
        self.repo_lb = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
        self.motor = motor
        self.servicio = IsolationService(self.repo, self.repo_lb, motor=motor, reloj=lambda: T0)

    def autorizar(self, mac):
        self.repo_lb.add(DispositivoConfiable(mac, "PC", T0, OrigenRegistro.ESCANEO, True))

    def disco(self):
        return json.loads(self.ruta.read_text(encoding="utf-8"))

    def estados(self, mac=MAC):
        return [(o.tipo.value, o.estado.value,
                 o.motivo_fallo.value if o.motivo_fallo else None)
                for o in self.repo.operaciones(mac)]


@pytest.fixture
def e(tmp_path):
    return Entorno(tmp_path, MotorSimulado())


# --- Máquina de estados (modelo) ----------------------------------------------

def _op(estado=EstadoOperacion.PENDING):
    op = OperacionAislamiento(MAC, TipoOperacion.AISLAR, ACTOR, T0)
    if estado is EstadoOperacion.PENDING:
        return op
    op = op.solicitar()
    if estado is EstadoOperacion.CONFIRMED:
        return op.confirmar(T0, "id")
    if estado is EstadoOperacion.FAILED:
        return op.fallar(MotivoFallo.SIN_CONFIRMACION, T0)
    return op


def test_tabla_de_transiciones():
    assert TRANSICIONES[EstadoOperacion.PENDING] == {EstadoOperacion.REQUESTED,
                                                     EstadoOperacion.FAILED}
    # UNCERTAIN se añadió para resultados de red desconocidos (requieren recuperación).
    assert TRANSICIONES[EstadoOperacion.REQUESTED] == {EstadoOperacion.CONFIRMED,
                                                       EstadoOperacion.FAILED,
                                                       EstadoOperacion.UNCERTAIN}
    assert TRANSICIONES[EstadoOperacion.CONFIRMED] == set()     # Terminal
    assert TRANSICIONES[EstadoOperacion.FAILED] == set()        # Terminal
    assert TRANSICIONES[EstadoOperacion.UNCERTAIN] == set()     # Terminal


def test_pending_no_puede_confirmarse_sin_solicitud():
    with pytest.raises(TransicionInvalidaError):
        _op().confirmar(T0)


@pytest.mark.parametrize("estado", [EstadoOperacion.CONFIRMED, EstadoOperacion.FAILED])
def test_estados_terminales_no_cambian(estado):
    op = _op(estado)
    with pytest.raises(TransicionInvalidaError):
        op.solicitar()
    with pytest.raises(TransicionInvalidaError):
        op.confirmar(T0)
    with pytest.raises(TransicionInvalidaError):
        op.fallar(MotivoFallo.ERROR_MOTOR, T0)


def test_motivos_de_fallo_segun_origen():
    # Antes de enviar al motor solo caben NO_DISPONIBLE / ERROR_REGISTRO.
    with pytest.raises(TransicionInvalidaError):
        _op().fallar(MotivoFallo.SIN_CONFIRMACION, T0)
    assert _op().fallar(MotivoFallo.NO_DISPONIBLE, T0).estado is EstadoOperacion.FAILED
    # Tras enviarla, NO_DISPONIBLE ya no es un motivo válido.
    with pytest.raises(TransicionInvalidaError):
        _op(EstadoOperacion.REQUESTED).fallar(MotivoFallo.NO_DISPONIBLE, T0)


def test_pending_no_se_persiste_ni_se_acepta_desde_disco():
    with pytest.raises(TransicionInvalidaError):
        _op().a_dict()
    datos = _op(EstadoOperacion.REQUESTED).a_dict()
    datos["estado"] = "PENDING"
    with pytest.raises(ValueError):
        OperacionAislamiento.desde_dict(datos)


@pytest.mark.parametrize("estado", [EstadoOperacion.REQUESTED, EstadoOperacion.CONFIRMED,
                                    EstadoOperacion.FAILED])
def test_operacion_ida_y_vuelta(estado):
    op = _op(estado)
    assert OperacionAislamiento.desde_dict(op.a_dict()) == op


# --- Lista blanca y ausencia de aislamiento automático ------------------------

def test_rechaza_mac_en_lista_blanca_sin_tocar_motor_ni_disco(e):
    e.autorizar(MAC)
    with pytest.raises(DispositivoProtegidoError):
        e.servicio.aislar(MAC.lower().replace(":", "-"), ACTOR)   # MAC sin normalizar
    assert e.motor.llamadas == []
    assert not e.ruta.exists()


def test_deteccion_de_desconocido_no_aisla_automaticamente(tmp_path):
    motor = MotorSimulado()
    ent = Entorno(tmp_path, motor)
    cfg = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
    cfg.seleccionar_interfaz(interfaz())
    cfg.activar_monitoreo()
    descubrimiento = DeviceDiscoveryService(SondaFalsa({"10.0.0.14": MAC, "10.0.0.30": MAC_2}),
                                            OuiFalso(), HostnamesFalso(),
                                            tiempo_maximo_hostname=0.1)
    monitoreo = MonitoringService(cfg, NetworkInterfaceService(ProveedorInterfacesFalso([interfaz()])),
                                  descubrimiento, WhitelistService(ent.repo_lb),
                                  aislamiento=ent.servicio)
    for _ in range(3):
        resultado = monitoreo.ejecutar_ciclo(threading.Event())
    assert resultado.tipo is TipoResultado.ACTUALIZADO
    assert {MAC, MAC_2} <= {p.mac for p in resultado.dispositivos}   # Desconocidos visibles
    assert motor.llamadas == []                                      # Nada se envió al motor
    assert not ent.ruta.exists()                                     # Nada se registró


@pytest.mark.parametrize("actor", ["", "   ", None])
def test_requiere_un_usuario_que_solicite(e, actor):
    with pytest.raises(AislamientoError):
        e.servicio.aislar(MAC, actor)
    assert e.motor.llamadas == []


# --- Solicitud y confirmación -------------------------------------------------

def test_solicitud_queda_requested_antes_de_llamar_al_motor(tmp_path):
    motor = MotorSimulado()
    ent = Entorno(tmp_path, motor)
    vistos = []
    original = motor.isolate

    def isolate(mac):
        # En el instante en que el motor recibe la orden, el disco ya tiene la
        # solicitud REQUESTED y la MAC aún NO figura como aislada.
        vistos.append((ent.estados(), ent.repo.macs_activas()))
        original(mac)

    motor.isolate = isolate
    ent.servicio.aislar(MAC, ACTOR)
    assert vistos == [([("AISLAR", "REQUESTED", None)], set())]
    assert ent.estados() == [("AISLAR", "CONFIRMED", None)]


def test_aislamiento_confirmado(e):
    accion = e.servicio.aislar(MAC, ACTOR)
    assert accion.activo and accion.autorizado_por == ACTOR
    assert e.servicio.macs_aisladas() == {MAC}
    op = e.repo.operaciones(MAC)[0]
    assert op.estado is EstadoOperacion.CONFIRMED and op.id_aislamiento == accion.id_aislamiento
    assert e.motor.llamadas == [("isolate", MAC)]


def test_no_se_aisla_dos_veces(e):
    e.servicio.aislar(MAC, ACTOR)
    with pytest.raises(TransicionNoPermitidaError):
        e.servicio.aislar(MAC, ACTOR)
    assert e.motor.llamadas == [("isolate", MAC)]


# --- Fallos y motor no disponible ---------------------------------------------

def test_motor_ausente_no_disponible(tmp_path):
    ent = Entorno(tmp_path, motor=None)
    with pytest.raises(AislamientoNoDisponibleError) as error:
        ent.servicio.aislar(MAC, ACTOR)
    op = error.value.operacion
    assert op.estado is EstadoOperacion.FAILED and op.motivo_fallo is MotivoFallo.NO_DISPONIBLE
    assert not ent.ruta.exists()      # Nada se envió: no hay operación que registrar


def test_motor_presente_pero_no_operativo(tmp_path):
    motor = MotorSimulado(disponible=False)
    ent = Entorno(tmp_path, motor)
    assert not ent.servicio.disponible
    with pytest.raises(AislamientoNoDisponibleError):
        ent.servicio.aislar(MAC, ACTOR)
    assert motor.llamadas == [] and not ent.ruta.exists()


# FAILED = efecto conocido (status contrario válido). UNCERTAIN = efecto desconocido
# (excepción, DESCONOCIDO o valor ajeno al contrato): requiere recuperación.
@pytest.mark.parametrize("motor, estado, motivo", [
    (MotorSimulado(falla_isolate=True), "UNCERTAIN", "ERROR_MOTOR"),
    (MotorSimulado(falla_status=True), "UNCERTAIN", "ERROR_MOTOR"),
    (MotorSimulado(confirma_aislar=False), "FAILED", "SIN_CONFIRMACION"),
    (MotorSimulado(estado_forzado=EstadoContencion.DESCONOCIDO), "UNCERTAIN", "SIN_CONFIRMACION"),
    (MotorSimulado(estado_forzado=EstadoContencion.SIN_CONTENCION), "FAILED", "SIN_CONFIRMACION"),
    (MotorSimulado(estado_forzado="AISLADO"), "UNCERTAIN", "SIN_CONFIRMACION"),  # Contrato antiguo
    (MotorSimulado(estado_forzado="CONTENCION_APLICADA"), "UNCERTAIN",
     "SIN_CONFIRMACION"),                                                        # Texto, no enum
    (MotorSimulado(estado_forzado=True), "UNCERTAIN", "SIN_CONFIRMACION"),
])
def test_sin_evidencia_no_hay_aislamiento_confirmado(tmp_path, motor, estado, motivo):
    ent = Entorno(tmp_path, motor)
    with pytest.raises(AislamientoFallidoError) as error:
        ent.servicio.aislar(MAC, ACTOR)
    assert error.value.operacion.motivo_fallo.value == motivo
    assert error.value.requiere_recuperacion is (estado == "UNCERTAIN")
    assert ent.servicio.macs_aisladas() == set()
    assert ent.disco()["aislamientos"] == []
    # El fallo queda en el historial (no se borra en silencio).
    assert ent.estados() == [("AISLAR", estado, motivo)]
    assert not ent.servicio.situacion(MAC).aislado_confirmado
    assert ent.servicio.requiere_recuperacion(MAC) is (estado == "UNCERTAIN")


def test_tras_un_fallo_se_puede_reintentar(tmp_path):
    motor = MotorSimulado(confirma_aislar=False)
    ent = Entorno(tmp_path, motor)
    with pytest.raises(AislamientoFallidoError):
        ent.servicio.aislar(MAC, ACTOR)
    motor.confirma_aislar = True
    ent.servicio.aislar(MAC, ACTOR)
    assert ent.estados() == [("AISLAR", "FAILED", "SIN_CONFIRMACION"),
                             ("AISLAR", "CONFIRMED", None)]


# --- Desbloqueo -----------------------------------------------------------------

def test_desbloqueo_exitoso(e):
    accion = e.servicio.aislar(MAC, ACTOR)
    finalizada = e.servicio.desbloquear(MAC, ACTOR)
    assert finalizada.id_aislamiento == accion.id_aislamiento and not finalizada.activo
    assert e.servicio.macs_aisladas() == set()
    assert e.estados() == [("AISLAR", "CONFIRMED", None), ("DESBLOQUEAR", "CONFIRMED", None)]
    registro = e.disco()["aislamientos"][0]
    assert registro["estado"] == "INACTIVO" and registro["fechaFin"] is not None


# Antes esta prueba exigía «Aislado (confirmado)» en los tres casos, incluso con
# el motor caído o respondiendo DESCONOCIDO: era el defecto H4 de la auditoría.
_INCIERTO_DESBLOQUEO = "Requiere recuperación: resultado incierto del último desbloqueo"


@pytest.mark.parametrize("cambios, estado, motivo, confirmado, texto", [
    ({"falla_release": True}, "UNCERTAIN", "ERROR_MOTOR", False,
     _INCIERTO_DESBLOQUEO + " (el motor informó DESCONOCIDO a las 09:00:00)"),
    ({"falla_status": True}, "UNCERTAIN", "ERROR_MOTOR", False,
     _INCIERTO_DESBLOQUEO + " (el motor informó DESCONOCIDO a las 09:00:00)"),
    ({"confirma_liberar": False}, "FAILED", "SIN_CONFIRMACION", True,   # sigue CONTENCION_APLICADA
     "Contención aplicada según el motor (verificado a las 09:00:00); el último desbloqueo falló"),
    ({"estado_forzado": EstadoContencion.DESCONOCIDO}, "UNCERTAIN", "SIN_CONFIRMACION", False,
     _INCIERTO_DESBLOQUEO + " (el motor informó DESCONOCIDO a las 09:00:00)"),
    ({"estado_forzado": "SIN_CONTENCION"}, "UNCERTAIN", "SIN_CONFIRMACION", False,  # Texto
     _INCIERTO_DESBLOQUEO + " (el motor informó DESCONOCIDO a las 09:00:00)"),
])
def test_desbloqueo_fallido_no_declara_conectividad_restaurada(e, cambios, estado, motivo,
                                                               confirmado, texto):
    e.servicio.aislar(MAC, ACTOR)
    for clave, valor in cambios.items():
        setattr(e.motor, clave, valor)
    with pytest.raises(DesbloqueoFallidoError):
        e.servicio.desbloquear(MAC, ACTOR)
    assert e.servicio.macs_aisladas() == {MAC}                     # Sigue aislado
    assert e.estados() == [("AISLAR", "CONFIRMED", None), ("DESBLOQUEAR", estado, motivo)]
    assert e.servicio.requiere_recuperacion(MAC) is (estado == "UNCERTAIN")
    situacion = e.servicio.situacion(MAC)
    assert situacion.registrado
    assert situacion.aislado_confirmado is confirmado
    assert formato.texto_situacion_aislamiento(situacion) == texto


def test_desbloqueo_sin_motor_no_disponible(tmp_path):
    ent = Entorno(tmp_path, MotorSimulado())
    ent.servicio.aislar(MAC, ACTOR)
    sin_motor = IsolationService(ent.repo, ent.repo_lb, motor=None, reloj=lambda: T0)
    with pytest.raises(AislamientoNoDisponibleError):
        sin_motor.desbloquear(MAC, ACTOR)
    assert sin_motor.macs_aisladas() == {MAC}
    assert ent.estados() == [("AISLAR", "CONFIRMED", None)]


def test_desbloquear_sin_aislamiento_se_rechaza(e):
    with pytest.raises(TransicionNoPermitidaError):
        e.servicio.desbloquear(MAC, ACTOR)
    assert e.motor.llamadas == []


def test_desbloqueo_no_depende_de_la_lista_blanca(e):
    # Autorización y aislamiento son independientes: un equipo aislado que luego
    # se autoriza puede desbloquearse; la lista blanca no cambia.
    e.servicio.aislar(MAC, ACTOR)
    e.autorizar(MAC)
    e.servicio.desbloquear(MAC, ACTOR)
    assert e.repo_lb.exists(MAC)
    assert e.servicio.macs_aisladas() == set()


# --- Concurrencia ---------------------------------------------------------------

def _en_hilo(funcion, *args):
    resultado = {}

    def ejecutar():
        try:
            resultado["valor"] = funcion(*args)
        except Exception as error:  # noqa: BLE001
            resultado["error"] = error

    hilo = threading.Thread(target=ejecutar, daemon=True)
    hilo.start()
    return hilo, resultado


def test_misma_mac_rechaza_duplicado_y_desbloqueo_simultaneo(e):
    liberar = e.motor.bloquear(MAC)
    hilo, resultado = _en_hilo(e.servicio.aislar, MAC, ACTOR)
    assert e.motor.dentro[MAC].wait(5)
    # Mientras el motor trabaja: la solicitud está REQUESTED, no confirmada.
    assert e.estados() == [("AISLAR", "REQUESTED", None)]
    assert e.servicio.macs_aisladas() == set()
    assert e.servicio.situacion(MAC).en_curso is TipoOperacion.AISLAR
    with pytest.raises(OperacionEnCursoError):
        e.servicio.aislar(MAC, ACTOR)                 # Duplicado
    with pytest.raises(OperacionEnCursoError):
        e.servicio.desbloquear(MAC, ACTOR)            # Operación incompatible
    liberar.set()
    hilo.join(5)
    assert "error" not in resultado
    assert e.motor.llamadas == [("isolate", MAC)]     # El motor recibió UNA sola orden
    assert e.estados() == [("AISLAR", "CONFIRMED", None)]


def test_carrera_de_muchos_hilos_sobre_la_misma_mac(e):
    barrera = threading.Barrier(8)
    resultados = []

    def intentar():
        barrera.wait()
        try:
            e.servicio.aislar(MAC, ACTOR)
            resultados.append("ok")
        except (OperacionEnCursoError, TransicionNoPermitidaError):
            resultados.append("rechazada")

    hilos = [threading.Thread(target=intentar) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(5)
    assert resultados.count("ok") == 1 and resultados.count("rechazada") == 7
    assert e.motor.llamadas == [("isolate", MAC)]
    assert len(e.disco()["aislamientos"]) == 1


def test_mac_distintas_son_independientes(e):
    liberar = e.motor.bloquear(MAC)
    hilo, resultado = _en_hilo(e.servicio.aislar, MAC, ACTOR)
    assert e.motor.dentro[MAC].wait(5)
    # MAC sigue bloqueada en el motor; MAC_2 se aísla y desbloquea sin esperar.
    e.servicio.aislar(MAC_2, ACTOR)
    assert e.servicio.macs_aisladas() == {MAC_2}
    e.servicio.desbloquear(MAC_2, ACTOR)
    liberar.set()
    hilo.join(5)
    assert "error" not in resultado
    assert e.servicio.macs_aisladas() == {MAC}
    assert e.estados(MAC_2) == [("AISLAR", "CONFIRMED", None), ("DESBLOQUEAR", "CONFIRMED", None)]


def test_la_reserva_se_libera_aunque_haya_excepcion(e):
    e.motor.falla_isolate = True
    with pytest.raises(AislamientoFallidoError):
        e.servicio.aislar(MAC, ACTOR)
    assert e.servicio.situacion(MAC).en_curso is None
    e.motor.falla_isolate = False
    e.servicio.aislar(MAC, ACTOR)                     # No quedó bloqueada
    assert e.servicio.macs_aisladas() == {MAC}


# --- Persistencia y recuperación ------------------------------------------------

def test_persistencia_y_recuperacion_desde_json(tmp_path, e):
    e.servicio.aislar(MAC, ACTOR)
    e.motor.confirma_aislar = False
    with pytest.raises(AislamientoFallidoError):
        e.servicio.aislar(MAC_2, ACTOR)
    # Un servicio nuevo sobre el mismo archivo (reinicio de la aplicación).
    nuevo = Entorno(tmp_path, MotorSimulado())
    assert nuevo.servicio.macs_aisladas() == {MAC}
    assert nuevo.estados(MAC) == [("AISLAR", "CONFIRMED", None)]
    assert nuevo.estados(MAC_2) == [("AISLAR", "FAILED", "SIN_CONFIRMACION")]
    datos = nuevo.disco()
    assert datos["version"] == 2
    # Solo MAC, fechas, actor y estados: ningún dato del inventario temporal.
    claves = set().union(*(o.keys() for o in datos["operaciones"]))
    assert not claves & {"ip", "hostname", "fabricante", "nombre"}


def test_lee_formato_version_1_y_lo_migra_sin_perder_registros(e):
    antiguo = AccionAislamiento(mac_objetivo=MAC_2, fecha_inicio=T0, autorizado_por="u")
    e.ruta.write_text(json.dumps({"version": 1, "aislamientos": [antiguo.a_dict()]}),
                      encoding="utf-8")
    assert e.servicio.macs_aisladas() == {MAC_2}
    assert e.repo.operaciones() == []
    e.servicio.aislar(MAC, ACTOR)
    datos = e.disco()
    assert datos["version"] == 2
    assert {a["macObjetivo"] for a in datos["aislamientos"]} == {MAC, MAC_2}


def test_operacion_interrumpida_se_recupera_como_fallida(tmp_path, e):
    # Simula un cierre a mitad: queda una solicitud REQUESTED en disco.
    solicitada = OperacionAislamiento(MAC, TipoOperacion.AISLAR, ACTOR, T0).solicitar()
    e.repo.registrar_solicitud(solicitada)
    nuevo = Entorno(tmp_path, MotorSimulado())
    assert nuevo.servicio.situacion(MAC).en_curso is TipoOperacion.AISLAR
    recuperadas = nuevo.servicio.recuperar_interrumpidas()
    assert [o.id_operacion for o in recuperadas] == [solicitada.id_operacion]
    # Resultado de red desconocido: UNCERTAIN (antes FAILED), pendiente de recuperación.
    assert nuevo.estados() == [("AISLAR", "UNCERTAIN", "INTERRUMPIDA")]
    assert nuevo.servicio.macs_aisladas() == set()   # Nunca se da por confirmada
    assert nuevo.servicio.requiere_recuperacion(MAC)
    assert formato.texto_situacion_aislamiento(nuevo.servicio.situacion(MAC)) == \
        "Requiere recuperación: resultado incierto del último aislamiento"
    nuevo.servicio.aislar(MAC, ACTOR)                # Y la MAC vuelve a estar operable
    assert not nuevo.servicio.requiere_recuperacion(MAC)   # Resuelta por un CONFIRMED


@pytest.mark.parametrize("contenido", ["{no es json", '{"version": 2}', '[]',
                                       '{"version": 99, "aislamientos": []}',
                                       '{"version": 2, "aislamientos": [], '
                                       '"operaciones": [{"estado": "CONFIRMED"}]}'])
def test_json_invalido_no_llama_al_motor_ni_sobrescribe(e, contenido):
    e.ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(RegistroAislamientoError):
        e.servicio.aislar(MAC, ACTOR)
    assert e.motor.llamadas == []
    assert e.ruta.read_text(encoding="utf-8") == contenido     # Intacto


def _fallar_escrituras(monkeypatch, desde: int):
    """Hace fallar os.replace a partir de la escritura número ``desde`` (1 = primera)."""
    original = json_file.os.replace
    cuenta = {"n": 0}

    def replace(origen, destino):
        cuenta["n"] += 1
        if cuenta["n"] >= desde:
            raise PermissionError("disco protegido contra escritura")
        return original(origen, destino)

    monkeypatch.setattr(json_file.os, "replace", replace)


def test_error_al_registrar_la_solicitud_no_invoca_al_motor(e, monkeypatch):
    e.servicio.aislar(MAC_2, ACTOR)                 # Contenido previo que debe conservarse
    previo = e.ruta.read_bytes()
    _fallar_escrituras(monkeypatch, desde=1)
    with pytest.raises(RegistroAislamientoError) as error:
        e.servicio.aislar(MAC, ACTOR)
    assert error.value.operacion.motivo_fallo is MotivoFallo.ERROR_REGISTRO
    assert ("isolate", MAC) not in e.motor.llamadas
    assert e.ruta.read_bytes() == previo
    assert not (e.ruta.parent / "aislamientos.json.tmp").exists()


def test_error_al_registrar_la_confirmacion_no_marca_aislado(tmp_path, e, monkeypatch):
    _fallar_escrituras(monkeypatch, desde=2)        # Se guarda REQUESTED; falla el resultado
    with pytest.raises(RegistroAislamientoError):
        e.servicio.aislar(MAC, ACTOR)
    monkeypatch.undo()
    assert e.servicio.macs_aisladas() == set()
    assert e.estados() == [("AISLAR", "REQUESTED", None)]
    assert e.servicio._reservas.en_curso(MAC) is None            # Reserva liberada
    # En disco sigue la solicitud sin resultado: se muestra como no confirmada.
    assert formato.texto_situacion_aislamiento(e.servicio.situacion(MAC)) == \
        "Aislamiento solicitado, sin confirmar"
    # La siguiente solicitud trata el REQUESTED huérfano como interrumpido.
    e.servicio.aislar(MAC, ACTOR)
    assert e.estados() == [("AISLAR", "UNCERTAIN", "INTERRUMPIDA"), ("AISLAR", "CONFIRMED", None)]
    confirmada = e.repo.operaciones(MAC)[1]
    assert e.repo.operaciones(MAC)[0].id_recuperacion == confirmada.id_operacion


def test_repositorio_rechaza_solicitudes_incoherentes(e):
    solicitada = OperacionAislamiento(MAC, TipoOperacion.AISLAR, ACTOR, T0).solicitar()
    e.repo.registrar_solicitud(solicitada)
    with pytest.raises(ValueError):    # Segunda solicitud en curso para la misma MAC
        e.repo.registrar_solicitud(
            OperacionAislamiento(MAC, TipoOperacion.AISLAR, ACTOR, T0).solicitar())
    with pytest.raises(ValueError):    # Desbloqueo sin contención activa
        e.repo.registrar_solicitud(
            OperacionAislamiento(MAC_2, TipoOperacion.DESBLOQUEAR, ACTOR, T0).solicitar())


# --- Integración con Dispositivos y Lista blanca -------------------------------

def test_integracion_dispositivos_lista_blanca(qapp, tmp_path, monkeypatch):
    from app.controllers.whitelist_controller import WhitelistController
    from presentation.views.edit_whitelist_dialog import ACCION_AISLAR
    from presentation.views.whitelist_view import WhitelistView

    motor = MotorSimulado()
    ent = Entorno(tmp_path, motor)
    lb = WhitelistService(ent.repo_lb)
    cfg = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
    cfg.seleccionar_interfaz(interfaz())
    cfg.activar_monitoreo()
    descubrimiento = DeviceDiscoveryService(SondaFalsa({"10.0.0.14": MAC, "10.0.0.30": MAC_2}),
                                            OuiFalso(), HostnamesFalso(),
                                            tiempo_maximo_hostname=0.1)
    monitoreo = MonitoringService(cfg, NetworkInterfaceService(ProveedorInterfacesFalso([interfaz()])),
                                  descubrimiento, lb, aislamiento=ent.servicio)
    monitoreo.ejecutar_ciclo(threading.Event())

    def visibles():
        return {p.mac for p in monitoreo.reclasificar()} & {MAC, MAC_2}

    # Dispositivos: una solicitud fallida NO retira el equipo de la tabla.
    motor.confirma_aislar = False
    with pytest.raises(AislamientoFallidoError):
        ent.servicio.aislar(MAC, ACTOR)
    assert visibles() == {MAC, MAC_2}
    # Confirmado: desaparece. Desbloqueo confirmado: reaparece.
    motor.confirma_aislar = True
    ent.servicio.aislar(MAC, ACTOR)
    assert visibles() == {MAC_2}
    ent.servicio.desbloquear(MAC, ACTOR)
    assert visibles() == {MAC, MAC_2}

    # Lista blanca: el diálogo muestra el estado real y el aislamiento se rechaza (RI-05).
    lb.autorizar(MAC_2, "TV")
    vista = WhitelistView()
    ctrl = WhitelistController(vista, lb, monitoreo, ent.servicio)
    datos_vistos, avisos = [], []

    def solicitar_edicion(datos):
        datos_vistos.append(datos)
        return ACCION_AISLAR, None

    monkeypatch.setattr(vista, "solicitar_edicion", solicitar_edicion)
    monkeypatch.setattr(vista, "confirmar_aislamiento", lambda alias, mac, ip: True)
    monkeypatch.setattr(vista, "advertir", lambda t, m: avisos.append((t, m)))
    llamadas_previas = list(motor.llamadas)
    vista.editarSolicitado.emit(MAC_2)
    assert datos_vistos[0].estado_aislamiento == "Sin aislamiento registrado"
    assert avisos and avisos[0][0] == "No se pudo aislar" and "RI-05" in avisos[0][1]
    assert motor.llamadas == llamadas_previas            # El motor no recibió nada
    assert lb.buscar(MAC_2) is not None                  # La autorización no cambió
    ctrl.deleteLater()


def test_controlador_dispositivos_distingue_fallo_de_no_disponible(qapp, tmp_path, monkeypatch):
    from test_controladores_gui import MAC_PC, App, _macs_en_tabla, esperar
    from presentation.views.review_dialog import ACCION_AISLAR

    for n, (motor, titulo) in enumerate([
            (None, "Aislamiento no disponible"),
            # Excepción del motor: efecto desconocido → requiere recuperación.
            (MotorSimulado(falla_isolate=True), "Resultado incierto: requiere recuperación"),
            (MotorSimulado(confirma_aislar=False), "Aislamiento fallido")]):
        carpeta = tmp_path / f"caso{n}"
        carpeta.mkdir(parents=True)
        a = App(carpeta, motor=motor)
        try:
            a.cfg.seleccionar_interfaz(interfaz())
            a.cfg.activar_monitoreo()
            a.monitoreo.iniciar()
            assert esperar(qapp, lambda: MAC_PC in _macs_en_tabla(a.vista_disp))
            monkeypatch.setattr(a.vista_disp, "solicitar_decision",
                                lambda perfil: (ACCION_AISLAR, None))
            monkeypatch.setattr(a.vista_disp, "confirmar_aislamiento", lambda perfil: True)
            avisos, informes = [], []
            monkeypatch.setattr(a.vista_disp, "advertir", lambda t, m: avisos.append(t))
            monkeypatch.setattr(a.vista_disp, "informar", lambda t, m: informes.append(t))
            a.vista_disp.revisarSolicitado.emit(MAC_PC)
            assert avisos == [titulo] and informes == []
            assert MAC_PC in _macs_en_tabla(a.vista_disp)
            assert a.repo_ais.macs_activas() == set()
        finally:
            a.cerrar()
