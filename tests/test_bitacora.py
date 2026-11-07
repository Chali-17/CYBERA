"""Pruebas del módulo Bitácora (historial de eventos, RF/CU del módulo).

Cubre: registro de los cinco tipos de evento, persistencia local en
``bitacora.json``, orden cronológico (más reciente primero), filtros por tipo y
rango de fechas (combinables, límites inclusivos), historial vacío, eventos sin
duplicados, resultados de aislamiento y flujo de depuración manual.
"""

import json
import threading
from datetime import date, datetime, timedelta

import pytest

from app.controllers.bitacora_controller import BitacoraController
from app.models.evento_bitacora import EventoBitacora, ResultadoEvento, TipoEvento, nuevo_id
from app.services.bitacora_service import BitacoraService
from app.services.device_discovery_service import DeviceDiscoveryService
from app.services.isolation_service import AislamientoFallidoError, IsolationService
from app.services.monitoring_service import MonitoringService, TipoResultado
from app.services.network_interface_service import NetworkInterfaceService
from app.services.settings_service import SettingsService
from app.services.whitelist_service import WhitelistService
from dobles import HostnamesFalso, OuiFalso, ProveedorInterfacesFalso, SondaFalsa, interfaz
from test_aislamiento import MotorDoble
from infrastructure.interfaces import INetworkIsolation
from infrastructure.persistence.bitacora_repository import JsonBitacoraRepository
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.persistence.json_file import ArchivoDatosError
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository
from presentation.views.bitacora_view import BitacoraView

MAC_ROUTER = "10:24:07:AA:E3:89"
MAC_PC = "50:9A:4C:4C:78:B2"
T0 = datetime(2026, 10, 20, 12, 0, 0)


def descubridor(sonda=None):
    return DeviceDiscoveryService(
        sonda or SondaFalsa({}),
        OuiFalso({}),
        HostnamesFalso(),
        nombre_equipo="ESTE-PC",
        tiempo_maximo_hostname=0.2)


# --- EventoBitacora (modelo) -----------------------------------------------------

def test_evento_bitacora_roundtrip_a_dict_y_desde_dict():
    evento = EventoBitacora(id=nuevo_id(), tipo=TipoEvento.BLOQUEO, fecha_hora=T0, mac_dispositivo=MAC_PC,
                             nombre_dispositivo="PC", descripcion="  Aislamiento  ",
                             resultado=ResultadoEvento.EXITOSO, actor="administrador")
    datos = evento.a_dict()
    assert datos["tipo"] == "BLOQUEO" and datos["resultado"] == "EXITOSO"
    assert datos["fechaHora"].endswith("T12:00:00")
    assert EventoBitacora.desde_dict(datos) == evento


def test_evento_bitacora_genera_id_unico_y_recorta_descripcion():
    assert nuevo_id() != nuevo_id()
    evento = EventoBitacora(id=nuevo_id(), tipo=TipoEvento.CONEXION, fecha_hora=T0,
                             descripcion="  Demasiados   espacios  ")
    assert evento.descripcion == "Demasiados espacios"


# --- Persistencia (JsonBitacoraRepository) --------------------------------------

def test_bitacora_se_persiste_en_archivo_y_sobrevive_un_reinicio(tmp_path):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    evento = servicio.registrar(TipoEvento.CONEXION, MAC_PC, "10.0.0.14", "DESKTOP-PRUEBA", None,
                                "Dispositivo detectado en la red local.")
    datos = json.loads((tmp_path / "bitacora.json").read_text(encoding="utf-8"))
    assert datos["version"] == 1 and isinstance(datos["eventos"], list) and len(datos["eventos"]) == 1
    assert datos["eventos"][0]["id"] == evento.id
    assert datos["eventos"][0]["tipo"] == "CONEXION"

    reiniciado = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    historial = reiniciado.historial()
    assert len(historial) == 1
    assert historial[0].mac_dispositivo == MAC_PC


def test_bitacora_repositorio_rechaza_eventos_duplicados(tmp_path):
    repo = JsonBitacoraRepository(tmp_path / "bitacora.json")
    evento = EventoBitacora(id=nuevo_id(), tipo=TipoEvento.DESCONEXION, fecha_hora=T0)
    assert repo.agregar(evento) is evento
    with pytest.raises(ValueError):
        repo.agregar(evento)


def test_bitacora_repositorio_archivo_danado_no_se_sobrescribe(tmp_path):
    ruta = tmp_path / "bitacora.json"
    ruta.write_text("dañado", encoding="utf-8")
    repo = JsonBitacoraRepository(ruta)
    with pytest.raises(ArchivoDatosError):
        repo.eventos()
    servicio = BitacoraService(repo)
    assert servicio.registrar(TipoEvento.BLOQUEO, MAC_PC, resultado=ResultadoEvento.EXITOSO) is not None
    assert ruta.read_text(encoding="utf-8") == "dañado"


# --- BitacoraService: registro ----------------------------------------------------

def test_registrar_conexion_crea_evento(tmp_path):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    evento = servicio.registrar_conexion(MAC_PC, "10.0.0.14", "DESKTOP-PRUEBA")
    assert evento.tipo is TipoEvento.CONEXION
    assert evento.mac_dispositivo == MAC_PC
    assert evento.ip_dispositivo == "10.0.0.14"
    assert evento.nombre_dispositivo == "DESKTOP-PRUEBA"
    assert evento.descripcion is not None and "detectado" in evento.descripcion
    assert evento.resultado is None


def test_registrar_desconexion_crea_evento(tmp_path):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    evento = servicio.registrar_desconexion(MAC_PC, "10.0.0.14")
    assert evento.tipo is TipoEvento.DESCONEXION
    assert evento.mac_dispositivo == MAC_PC
    assert evento.descripcion is not None and "dejó" in evento.descripcion


def test_registrar_bloqueo_exitoso_y_fallido(tmp_path):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    exitoso = servicio.registrar_bloqueo(MAC_PC, actor="administrador", resultado=ResultadoEvento.EXITOSO)
    fallido = servicio.registrar_bloqueo(MAC_PC, actor="administrador", resultado=ResultadoEvento.FALLO)
    assert exitoso.tipo is TipoEvento.BLOQUEO and exitoso.resultado is ResultadoEvento.EXITOSO
    assert fallido.tipo is TipoEvento.BLOQUEO and fallido.resultado is ResultadoEvento.FALLO


def test_registrar_desbloqueo_crea_evento(tmp_path):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    evento = servicio.registrar_desbloqueo(MAC_PC, actor="administrador", resultado=ResultadoEvento.EXITOSO)
    assert evento.tipo is TipoEvento.DESBLOQUEO
    assert evento.resultado is ResultadoEvento.EXITOSO


def test_registrar_autorizacion_dispositivo(tmp_path):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    evento = servicio.registrar_autorizacion(MAC_PC, alias="Laptop")
    assert evento.tipo is TipoEvento.AUTORIZACION_DISPOSITIVO
    assert evento.mac_dispositivo == MAC_PC
    assert evento.descripcion is not None and "Laptop" in evento.descripcion


def test_registrar_error_de_persistencia_no_propaga(tmp_path):
    class RepositorioQueFalla:
        def agregar(self, evento):
            raise RuntimeError("disco bloqueado")

    servicio = BitacoraService(RepositorioQueFalla())
    assert servicio.registrar(TipoEvento.CONEXION, MAC_PC) is not None


# --- BitacoraService: consulta ----------------------------------------------------

def test_historial_vacio_para_archivo_nuevo(tmp_path):
    assert BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json")).historial() == []


def test_historial_orden_mas_reciente_primero_y_rango_inclusive(tmp_path):
    ahora = {"valor": T0}

    def reloj():
        ahora["valor"] = ahora["valor"] + timedelta(minutes=1)
        return ahora["valor"]

    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"), reloj=reloj)
    primero = servicio.registrar(TipoEvento.CONEXION, MAC_PC)
    segundo = servicio.registrar(TipoEvento.BLOQUEO, MAC_PC, resultado=ResultadoEvento.EXITOSO)
    tercero = servicio.registrar(TipoEvento.DESCONEXION, MAC_PC)
    assert tercero.fecha_hora > segundo.fecha_hora > primero.fecha_hora

    assert [e.tipo for e in servicio.historial()] == [TipoEvento.DESCONEXION, TipoEvento.BLOQUEO,
                                                      TipoEvento.CONEXION]

    # Los límites del rango son inclusivos.
    resultados = servicio.historial(desde=segundo.fecha_hora, hasta=tercero.fecha_hora)
    assert [e.tipo for e in resultados] == [TipoEvento.DESCONEXION, TipoEvento.BLOQUEO]


def test_historial_rango_invalido_no_devuelve_resultados(tmp_path):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    servicio.registrar(TipoEvento.CONEXION, MAC_PC)
    assert servicio.historial(desde=datetime(2026, 10, 21), hasta=datetime(2026, 10, 20)) == []


def test_historial_filtra_por_tipo(tmp_path):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    servicio.registrar(TipoEvento.CONEXION, MAC_PC)
    servicio.registrar(TipoEvento.BLOQUEO, MAC_PC, resultado=ResultadoEvento.EXITOSO)
    assert [e.tipo for e in servicio.historial(tipo=TipoEvento.BLOQUEO)] == [TipoEvento.BLOQUEO]
    assert [e.tipo for e in servicio.historial(tipo=TipoEvento.CONEXION)] == [TipoEvento.CONEXION]


def test_historial_filtros_combinados(tmp_path):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    servicio.registrar(TipoEvento.CONEXION, MAC_PC, "10.0.0.14", "PC", None,
                       "Dispositivo detectado en la red local.")
    servicio.registrar(TipoEvento.BLOQUEO, MAC_PC, resultado=ResultadoEvento.EXITOSO)
    servicio.registrar(TipoEvento.DESCONEXION, MAC_PC)

    desde = datetime(2026, 1, 1)
    hasta = datetime(2027, 1, 1)
    assert [e.tipo for e in servicio.historial(tipo=TipoEvento.BLOQUEO,
                                               desde=desde, hasta=hasta)] == [TipoEvento.BLOQUEO]
    conexiones = servicio.historial(tipo=TipoEvento.CONEXION, desde=desde, hasta=hasta)
    assert len(conexiones) == 1
    assert conexiones[0].mac_dispositivo == MAC_PC


# --- Integración: aislamiento registra BLOQUEO / DESBLOQUEO -----------------------

def _aislamiento(tmp_path, motor: INetworkIsolation, bitacora: BitacoraService):
    repo_isol = JsonIsolationRepository(tmp_path / "aislamientos.json")
    repo_lb = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
    servicio = IsolationService(repo_isol, repo_lb, motor=motor, bitacora=bitacora)
    return servicio, repo_isol, repo_lb


def test_aislamiento_confirmado_registra_bloqueo_en_bitacora(tmp_path):
    bitacora = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    servicio, _, _ = _aislamiento(tmp_path, MotorDoble(confirma=True), bitacora)
    accion = servicio.aislar(MAC_PC, "administrador")
    assert accion.activo
    eventos = bitacora.historial()
    assert len(eventos) == 1
    assert eventos[0].tipo is TipoEvento.BLOQUEO
    assert eventos[0].resultado is ResultadoEvento.EXITOSO
    assert eventos[0].mac_dispositivo == MAC_PC
    assert eventos[0].actor == "administrador"


def test_aislamiento_fallido_registra_bloqueo_como_fallo(tmp_path):
    bitacora = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    servicio, _, _ = _aislamiento(tmp_path, MotorDoble(falla_isolate=True), bitacora)
    with pytest.raises(AislamientoFallidoError):
        servicio.aislar(MAC_PC, "administrador")
    eventos = bitacora.historial()
    assert len(eventos) == 1
    assert eventos[0].tipo is TipoEvento.BLOQUEO
    assert eventos[0].resultado is ResultadoEvento.FALLO


def test_desbloqueo_confirmado_registra_desbloqueo_en_bitacora(tmp_path):
    ahora = {"valor": T0}

    def reloj():
        ahora["valor"] = ahora["valor"] + timedelta(minutes=1)
        return ahora["valor"]

    bitacora = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"), reloj=reloj)
    servicio, _, _ = _aislamiento(tmp_path, MotorDoble(confirma=True), bitacora)
    servicio.aislar(MAC_PC, "administrador")
    servicio.desbloquear(MAC_PC, "administrador")
    assert [e.tipo for e in bitacora.historial()] == [TipoEvento.DESBLOQUEO, TipoEvento.BLOQUEO]


# --- Integración: monitoreo registra CONEXION sin duplicados ----------------------

def _entorno_bitacora(tmp_path):
    proveedor = ProveedorInterfacesFalso([interfaz()])
    sonda = SondaFalsa({"10.0.0.14": MAC_PC})
    configuracion = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
    lb = WhitelistService(JsonWhitelistRepository(tmp_path / "lista_blanca.json"))
    aislamiento = IsolationService(JsonIsolationRepository(tmp_path / "aislamientos.json"),
                                   JsonWhitelistRepository(tmp_path / "lista_blanca.json"))
    bitacora = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    servicio = MonitoringService(configuracion, NetworkInterfaceService(proveedor),
                                 descubridor(sonda=sonda), lb, aislamiento=aislamiento,
                                 bitacora=bitacora)
    return servicio, bitacora, configuracion


def test_monitoreo_registra_conexion_y_no_repite_eventos(tmp_path):
    servicio, bitacora, configuracion = _entorno_bitacora(tmp_path)
    configuracion.seleccionar_interfaz(interfaz())
    configuracion.activar_monitoreo()
    primero = servicio.ejecutar_ciclo(threading.Event())
    assert primero.tipo is TipoResultado.ACTUALIZADO
    assert len(bitacora.historial()) == 1

    segundo = servicio.ejecutar_ciclo(threading.Event())
    assert segundo.tipo is TipoResultado.ACTUALIZADO
    assert len(bitacora.historial()) == 1
    assert bitacora.historial()[0].tipo is TipoEvento.CONEXION


# --- Controlador y vista de la Bitácora ------------------------------------------

def _vista_con_controlador(servicio: BitacoraService, qapp):
    vista = BitacoraView()
    controlador = BitacoraController(vista, servicio)
    controlador.recargar()
    return vista, controlador


def test_bitacora_controller_recarga_eventos_en_la_vista(qapp, tmp_path):
    ahora = {"valor": T0}

    def reloj():
        ahora["valor"] = ahora["valor"] + timedelta(minutes=1)
        return ahora["valor"]

    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"), reloj=reloj)
    servicio.registrar(TipoEvento.CONEXION, MAC_PC, "10.0.0.14", "PC")
    servicio.registrar(TipoEvento.BLOQUEO, MAC_PC, resultado=ResultadoEvento.EXITOSO)
    vista, controlador = _vista_con_controlador(servicio, qapp)
    try:
        controlador.recargar()
        assert vista._tabla.rowCount() == 2
        assert vista._pila.currentWidget() is vista._tabla
        assert vista._tabla.item(0, 1).text() == "Aislamiento"  # Más reciente primero.
        assert vista._tabla.item(0, 4).text() == "Exitoso"
        assert vista._tabla.item(1, 4).text() == "Registrado"
    finally:
        controlador._bitacora.depurar()


def test_bitacora_controller_muestra_error_cuando_no_puede_leer(qapp, tmp_path):
    class RepositorioQueFalla:
        def historial(self, **kwargs):
            raise RuntimeError("bitacora ilegible")

        def vaciar(self):
            raise RuntimeError("bitacora ilegible")

    servicio = BitacoraService(RepositorioQueFalla())
    vista = BitacoraView()
    controlador = BitacoraController(vista, servicio)
    controlador.recargar()
    assert vista._pila.currentWidget() is vista._mensaje
    assert vista._mensaje.property("error") == "true"


def test_bitacora_controller_depura_tras_confirmacion(qapp, tmp_path, monkeypatch):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    servicio.registrar(TipoEvento.CONEXION, MAC_PC)
    vista = BitacoraView()
    controlador = BitacoraController(vista, servicio)
    monkeypatch.setattr(BitacoraView, "confirmar_depuracion", lambda self: True)
    monkeypatch.setattr(BitacoraView, "informar", lambda self, titulo, texto: None)
    controlador._solicitar_depuracion()
    assert servicio.historial() == []


def test_bitacora_controller_depura_respetando_el_cancel(qapp, tmp_path, monkeypatch):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    servicio.registrar(TipoEvento.CONEXION, MAC_PC)
    vista = BitacoraView()
    controlador = BitacoraController(vista, servicio)
    monkeypatch.setattr(BitacoraView, "confirmar_depuracion", lambda self: False)
    controlador._solicitar_depuracion()
    assert len(servicio.historial()) == 1


def test_bitacora_controller_no_ejecuta_la_depuracion_dos_veces(qapp, tmp_path, monkeypatch):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    servicio.registrar(TipoEvento.CONEXION, MAC_PC)
    vista = BitacoraView()
    controlador = BitacoraController(vista, servicio)
    monkeypatch.setattr(BitacoraView, "confirmar_depuracion", lambda self: True)
    monkeypatch.setattr(BitacoraView, "informar", lambda self, titulo, texto: None)
    controlador._enviando_depuracion = True
    controlador._solicitar_depuracion()      # Guard: la acción bloqueada no ejecuta nada.
    assert len(servicio.historial()) == 1
    controlador._enviando_depuracion = False
    controlador._solicitar_depuracion()      # Ahora sí ejecuta la depuración manual.
    assert servicio.historial() == []


def test_bitacora_controller_reanuda_el_guard_tras_la_operacion(qapp, tmp_path, monkeypatch):
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"))
    vista = BitacoraView()
    controlador = BitacoraController(vista, servicio)
    monkeypatch.setattr(BitacoraView, "confirmar_depuracion", lambda self: False)
    monkeypatch.setattr(BitacoraView, "informar", lambda self, titulo, texto: None)
    controlador._solicitar_depuracion()          # Historial vacío: el guard vuelve a False.
    servicio.registrar(TipoEvento.CONEXION, MAC_PC)
    controlador._solicitar_depuracion()          # Cancela: el guard vuelve a False.
    assert controlador._enviando_depuracion is False


# --- Vista: tipos y rango ---------------------------------------------------------

def test_vista_bitacora_combina_tipos_y_rango(qapp):
    from PySide6.QtCore import QDate
    vista = BitacoraView()
    assert vista.tipo() is None                                    # «Todos».
    assert vista.combo_tipo.itemText(0) == "Todos"
    assert vista.combo_tipo.itemText(1) == "Conexión"
    assert vista.combo_tipo.itemText(5) == "Autorización"
    vista.combo_tipo.setCurrentIndex(1)
    assert vista.tipo() is TipoEvento.CONEXION

    assert vista.rango() == (None, None)                          # Sin periodo: todo.
    vista.establecer_rango(date(2026, 10, 20), date(2026, 10, 21))
    desde, hasta = vista.rango()
    assert desde == datetime(2026, 10, 20, 0, 0, 0)
    assert hasta == datetime(2026, 10, 21, 23, 59, 59)            # Incluye todo el último día.
    assert vista.boton_rango.text() == "20/10/2026  –  21/10/2026"
    vista.establecer_rango(None, None)
    assert vista.rango() == (None, None)


def test_bitacora_filtra_por_rango_incluyendo_la_ultima_hora(qapp, tmp_path):
    reloj = iter([datetime(2026, 10, 21, 23, 30, 0), datetime(2026, 10, 22, 9, 0, 0)])
    servicio = BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json"),
                               reloj=lambda: next(reloj))
    servicio.registrar(TipoEvento.CONEXION, MAC_PC)
    servicio.registrar(TipoEvento.DESCONEXION, MAC_PC)
    vista, controlador = _vista_con_controlador(servicio, qapp)
    vista.establecer_rango(date(2026, 10, 21), date(2026, 10, 21))
    assert vista._tabla.rowCount() == 1
    assert vista._tabla.item(0, 1).text() == "Conexión"
    vista.combo_tipo.setCurrentIndex(2)                            # Desconexión: sin coincidencias.
    assert vista._pila.currentWidget() is vista._mensaje
    assert "filtros" in vista._mensaje.text()


def test_vista_bitacora_no_tiene_controles_de_exportacion(qapp):
    from PySide6.QtWidgets import QPushButton
    vista = BitacoraView()
    botones = [b for b in vista.findChildren(QPushButton) if "export" in b.text().lower()]
    assert botones == []                 # La exportación vive exclusivamente en Reportes.
