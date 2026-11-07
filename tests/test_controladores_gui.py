"""Pruebas de integración MVC con Qt (plataforma offscreen) y red simulada."""

import json
import time

import pytest
from PySide6.QtCore import QTimer

from app.controllers.device_controller import DeviceController
from app.controllers.monitoring_controller import EstadoIndicador, MonitoringController
from app.controllers.settings_controller import SettingsController
from app.models.interfaz_red import TipoInterfaz
from app.services.device_discovery_service import DeviceDiscoveryService
from app.services.isolation_service import IsolationService
from app.services.monitoring_service import MonitoringService, TipoResultado
from app.services.network_interface_service import NetworkInterfaceService
from app.services.settings_service import SettingsService
from app.services.whitelist_service import WhitelistService
from dobles import HostnamesFalso, OuiFalso, ProveedorInterfacesFalso, SondaFalsa, interfaz
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository
from presentation.views.device_view import DeviceView
from presentation.views.main_window import MainWindow
from presentation.views.review_dialog import ACCION_AISLAR, ACCION_AUTORIZAR
from presentation.views.settings_view import SettingsView
from test_aislamiento import MotorDoble

MAC_PC = "50:9A:4C:4C:78:B2"
MAC_TV = "AC:00:00:00:00:30"


def esperar(qapp, condicion, limite=10.0):
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        qapp.processEvents()
        if condicion():
            return True
        time.sleep(0.01)
    return False


class App:
    def __init__(self, tmp_path, demora=0.0, motor=None):
        self.dir = tmp_path
        self.proveedor = ProveedorInterfacesFalso([interfaz(),
                                                   interfaz(id_="{GUID-ETH}", nombre="Ethernet",
                                                            conectada=False, ip=None, prefijo=None,
                                                            tipo=TipoInterfaz.ETHERNET)])
        self.sonda = SondaFalsa({"10.0.0.14": MAC_PC, "10.0.0.30": MAC_TV}, demora=demora)
        self.cfg = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
        self.repo_lb = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
        self.lb = WhitelistService(self.repo_lb)
        self.repo_ais = JsonIsolationRepository(tmp_path / "aislamientos.json")
        # motor=None → aislamiento no disponible (como en producción). Un MotorDoble
        # permite probar el camino de éxito de forma SIMULADA.
        self.aislamiento = IsolationService(self.repo_ais, self.repo_lb, motor=motor)
        interfaces = NetworkInterfaceService(self.proveedor)
        descubrimiento = DeviceDiscoveryService(self.sonda, OuiFalso({"50:9A:4C": "Dell Inc."}),
                                                HostnamesFalso(), tiempo_maximo_hostname=0.2)
        self.servicio = MonitoringService(self.cfg, interfaces, descubrimiento, self.lb,
                                          aislamiento=self.aislamiento)
        self.vista_disp = DeviceView()
        self.vista_cfg = SettingsView()
        self.ventana = MainWindow({"Dispositivos": self.vista_disp, "Configuración": self.vista_cfg})
        self.monitoreo = MonitoringController(self.servicio, self.cfg, intervalo_s=0.2)
        self.dispositivos = DeviceController(self.vista_disp, self.monitoreo, self.servicio,
                                             self.lb, self.aislamiento)
        self.config = SettingsController(self.vista_cfg, self.cfg, interfaces)
        self.monitoreo.indicadorCambiado.connect(self.ventana.set_indicador)
        self.config.configuracionCambiada.connect(self.monitoreo.reevaluar)
        self.resultados = []
        self.monitoreo.resultadoCiclo.connect(self.resultados.append)

    def actualizados(self):
        return [r for r in self.resultados if r.tipo is TipoResultado.ACTUALIZADO]

    def cerrar(self):
        self.monitoreo.detener()
        self.config.detener()


@pytest.fixture
def app(qapp, tmp_path):
    a = App(tmp_path)
    yield a
    a.cerrar()


def test_monitoreo_inactivo_no_inicia_escaneos(qapp, app):
    app.cfg.seleccionar_interfaz(interfaz())
    app.monitoreo.iniciar()
    esperar(qapp, lambda: False, limite=1.0)
    assert app.sonda.sondeos == []
    assert app.vista_disp.indicador.property("estado") == "INACTIVO"
    assert "inactivo" in app.vista_disp._mensaje.text().lower()


def test_monitoreo_activo_llena_la_tabla(qapp, app):
    app.cfg.seleccionar_interfaz(interfaz())
    app.cfg.activar_monitoreo()
    app.monitoreo.iniciar()
    assert esperar(qapp, lambda: app.vista_disp.filas == 3)   # PC, TV y este equipo
    tabla = app.vista_disp._tabla
    filas = {tabla.item(f, 2).text(): f for f in range(tabla.rowCount())}
    fila_pc = filas[MAC_PC]
    assert tabla.item(fila_pc, 0).text() == "Desconocido"
    assert tabla.item(fila_pc, 3).text() == "Dell Inc."
    assert tabla.item(filas[MAC_TV], 3).text() == "No disponible"
    assert tabla.item(fila_pc, 4).text() == "Desconocido"
    assert app.ventana.botones["Dispositivos"].isChecked()
    assert app.vista_disp.indicador.property("estado") == "ACTIVO"


def test_la_interfaz_no_se_bloquea_durante_el_escaneo(qapp, tmp_path):
    a = App(tmp_path, demora=2.0)
    try:
        a.cfg.seleccionar_interfaz(interfaz())
        a.cfg.activar_monitoreo()
        latidos = []
        reloj = QTimer()
        reloj.timeout.connect(lambda: latidos.append(time.monotonic()))
        reloj.start(50)
        a.monitoreo.iniciar()
        assert esperar(qapp, lambda: a.actualizados(), limite=10)
        reloj.stop()
        # El bucle de eventos siguió procesando durante los 2 s de escaneo.
        assert len(latidos) >= 20
        assert max(b - a_ for a_, b in zip(latidos, latidos[1:])) < 0.5
    finally:
        a.cerrar()


def test_desactivar_durante_escaneo_descarta_resultados(qapp, tmp_path):
    a = App(tmp_path, demora=1.0)
    try:
        a.cfg.seleccionar_interfaz(interfaz())
        a.cfg.activar_monitoreo()
        a.monitoreo.iniciar()
        assert esperar(qapp, lambda: len(a.sonda.sondeos) == 1)
        a.cfg.desactivar_monitoreo()
        a.monitoreo.reevaluar()
        esperar(qapp, lambda: False, limite=2.0)
        assert a.actualizados() == []
        assert a.vista_disp.filas == 0
        assert len(a.sonda.sondeos) == 1          # No se lanzó ningún escaneo nuevo
    finally:
        a.cerrar()


def _macs_en_tabla(vista):
    tabla = vista._tabla
    return {tabla.item(f, 2).text() for f in range(tabla.rowCount())}


def test_autorizar_retira_el_dispositivo_de_la_tabla(qapp, app, monkeypatch):
    app.cfg.seleccionar_interfaz(interfaz())
    app.cfg.activar_monitoreo()
    app.monitoreo.iniciar()
    assert esperar(qapp, lambda: MAC_PC in _macs_en_tabla(app.vista_disp))
    monkeypatch.setattr(app.vista_disp, "solicitar_decision",
                        lambda perfil: (ACCION_AUTORIZAR, "Laptop"))
    mensajes = []
    monkeypatch.setattr(app.vista_disp, "informar", lambda t, m: mensajes.append(m))
    app.vista_disp.revisarSolicitado.emit(MAC_PC)

    datos = json.loads((app.dir / "lista_blanca.json").read_text(encoding="utf-8"))
    assert [(d["mac"], d["alias"], d["origenRegistro"]) for d in datos["dispositivos"]] == \
        [(MAC_PC, "Laptop", "ESCANEO")]
    assert MAC_PC not in _macs_en_tabla(app.vista_disp)   # Desaparece tras confirmar el éxito
    assert MAC_TV in _macs_en_tabla(app.vista_disp)       # Los demás siguen
    assert mensajes


def test_autorizar_fallido_mantiene_el_dispositivo(qapp, app, monkeypatch):
    app.cfg.seleccionar_interfaz(interfaz())
    app.cfg.activar_monitoreo()
    app.monitoreo.iniciar()
    assert esperar(qapp, lambda: MAC_PC in _macs_en_tabla(app.vista_disp))
    monkeypatch.setattr(app.vista_disp, "solicitar_decision",
                        lambda perfil: (ACCION_AUTORIZAR, None))

    def falla(*a, **k):
        raise OSError("disco protegido")
    monkeypatch.setattr(app.lb, "autorizar", falla)
    avisos = []
    monkeypatch.setattr(app.vista_disp, "advertir", lambda t, m: avisos.append(m))
    app.vista_disp.revisarSolicitado.emit(MAC_PC)
    assert MAC_PC in _macs_en_tabla(app.vista_disp)       # No desaparece si falla
    assert avisos


def test_cancelar_revision_no_modifica_lista_blanca(qapp, app, monkeypatch):
    app.cfg.seleccionar_interfaz(interfaz())
    app.cfg.activar_monitoreo()
    app.monitoreo.iniciar()
    assert esperar(qapp, lambda: MAC_PC in _macs_en_tabla(app.vista_disp))
    monkeypatch.setattr(app.vista_disp, "solicitar_decision", lambda perfil: (None, None))
    app.vista_disp.revisarSolicitado.emit(MAC_PC)
    assert not (app.dir / "lista_blanca.json").exists()
    assert MAC_PC in _macs_en_tabla(app.vista_disp)


def test_aislar_sin_motor_no_aisla_ni_retira(qapp, app, monkeypatch):
    # app usa motor=None (como producción): el aislamiento no está disponible.
    app.cfg.seleccionar_interfaz(interfaz())
    app.cfg.activar_monitoreo()
    app.monitoreo.iniciar()
    assert esperar(qapp, lambda: MAC_PC in _macs_en_tabla(app.vista_disp))
    monkeypatch.setattr(app.vista_disp, "solicitar_decision", lambda perfil: (ACCION_AISLAR, None))
    monkeypatch.setattr(app.vista_disp, "confirmar_aislamiento", lambda perfil: True)
    avisos = []
    monkeypatch.setattr(app.vista_disp, "advertir", lambda t, m: avisos.append((t, m)))
    app.vista_disp.revisarSolicitado.emit(MAC_PC)
    assert MAC_PC in _macs_en_tabla(app.vista_disp)       # Sigue visible
    assert not (app.dir / "aislamientos.json").exists()   # No se persistió nada
    assert any("disponible" in m.lower() for _, m in avisos)


def test_aislar_confirmado_retira_el_dispositivo(qapp, tmp_path, monkeypatch):
    # Motor SIMULADO que confirma el aislamiento (no es el motor real de red).
    a = App(tmp_path, motor=MotorDoble(confirma=True))
    try:
        a.cfg.seleccionar_interfaz(interfaz())
        a.cfg.activar_monitoreo()
        a.monitoreo.iniciar()
        assert esperar(qapp, lambda: MAC_PC in _macs_en_tabla(a.vista_disp))
        monkeypatch.setattr(a.vista_disp, "solicitar_decision", lambda perfil: (ACCION_AISLAR, None))
        monkeypatch.setattr(a.vista_disp, "confirmar_aislamiento", lambda perfil: True)
        monkeypatch.setattr(a.vista_disp, "informar", lambda t, m: None)
        a.vista_disp.revisarSolicitado.emit(MAC_PC)
        assert a.repo_ais.macs_activas() == {MAC_PC}       # Registrado tras confirmar el motor
        assert MAC_PC not in _macs_en_tabla(a.vista_disp)  # Desaparece de la tabla
        assert MAC_TV in _macs_en_tabla(a.vista_disp)
    finally:
        a.cerrar()


def test_aislar_fallido_mantiene_el_dispositivo(qapp, tmp_path, monkeypatch):
    # Motor que NO confirma: el servicio reporta fallo y no marca aislado.
    a = App(tmp_path, motor=MotorDoble(confirma=False))
    try:
        a.cfg.seleccionar_interfaz(interfaz())
        a.cfg.activar_monitoreo()
        a.monitoreo.iniciar()
        assert esperar(qapp, lambda: MAC_PC in _macs_en_tabla(a.vista_disp))
        monkeypatch.setattr(a.vista_disp, "solicitar_decision", lambda perfil: (ACCION_AISLAR, None))
        monkeypatch.setattr(a.vista_disp, "confirmar_aislamiento", lambda perfil: True)
        avisos = []
        monkeypatch.setattr(a.vista_disp, "advertir", lambda t, m: avisos.append(m))
        a.vista_disp.revisarSolicitado.emit(MAC_PC)
        assert MAC_PC in _macs_en_tabla(a.vista_disp)      # No desaparece
        assert a.repo_ais.macs_activas() == set()          # No se marcó como aislado
        assert avisos
    finally:
        a.cerrar()


def test_cancelar_confirmacion_de_aislamiento_no_hace_nada(qapp, app, monkeypatch):
    app.cfg.seleccionar_interfaz(interfaz())
    app.cfg.activar_monitoreo()
    app.monitoreo.iniciar()
    assert esperar(qapp, lambda: MAC_PC in _macs_en_tabla(app.vista_disp))
    monkeypatch.setattr(app.vista_disp, "solicitar_decision", lambda perfil: (ACCION_AISLAR, None))
    monkeypatch.setattr(app.vista_disp, "confirmar_aislamiento", lambda perfil: False)  # Cancela
    app.vista_disp.revisarSolicitado.emit(MAC_PC)
    assert MAC_PC in _macs_en_tabla(app.vista_disp)
    assert not (app.dir / "aislamientos.json").exists()


def test_configuracion_selecciona_interfaz_y_activa(qapp, app):
    app.monitoreo.iniciar()
    app.ventana.ir_a("Configuración")
    app.ventana.show()
    assert esperar(qapp, lambda: app.vista_cfg.combo_interfaz.isEnabled())
    combo = app.vista_cfg.combo_interfaz
    assert not app.vista_cfg.boton_monitoreo.isEnabled()     # Sin interfaz no se puede activar
    indice = combo.findData("{GUID-WIFI}")
    combo.setCurrentIndex(indice)
    combo.activated.emit(indice)
    assert app.cfg.cargar().interfaz_id == "{GUID-WIFI}"
    app.vista_cfg.boton_monitoreo.click()
    assert app.cfg.cargar().monitoreo_activo
    assert esperar(qapp, lambda: app.actualizados())
    assert app.vista_cfg.indicador.property("estado") == "ACTIVO"
    app.vista_cfg.boton_monitoreo.click()
    assert not app.cfg.cargar().monitoreo_activo
    assert app.vista_disp.filas == 0
    assert app.vista_cfg.indicador.property("estado") == "INACTIVO"
    app.ventana.hide()


def test_no_activa_con_interfaz_desconectada(qapp, app):
    app.monitoreo.iniciar()
    app.ventana.ir_a("Configuración")
    app.ventana.show()
    assert esperar(qapp, lambda: app.vista_cfg.combo_interfaz.isEnabled())
    combo = app.vista_cfg.combo_interfaz
    indice = combo.findData("{GUID-ETH}")
    combo.setCurrentIndex(indice)
    combo.activated.emit(indice)
    app.vista_cfg.boton_monitoreo.click()
    assert not app.cfg.cargar().monitoreo_activo
    assert "desconectada" in app.vista_cfg.aviso.text()
    assert app.sonda.sondeos == []
    app.ventana.hide()


def test_el_inventario_no_se_guarda_en_disco(qapp, app):
    app.cfg.seleccionar_interfaz(interfaz())
    app.cfg.activar_monitoreo()
    app.monitoreo.iniciar()
    assert esperar(qapp, lambda: len(app.actualizados()) >= 2)
    app.cerrar()
    archivos = sorted(p.name for p in app.dir.iterdir())
    assert archivos == ["configuracion.json"]
    contenido = (app.dir / "configuracion.json").read_text(encoding="utf-8")
    assert MAC_PC not in contenido and MAC_TV not in contenido
    assert app.servicio.reclasificar() == []               # Memoria liberada al cerrar


def test_navegacion_estatica(qapp, app):
    assert set(app.ventana.botones) == {"Dispositivos", "Configuración"}


def test_alertas_retirada_de_la_navegacion(qapp):
    from presentation.views.main_window import OPCIONES

    # «Alertas» fue retirada del alcance: ni como opción activa ni como etiqueta estática.
    assert "Alertas" not in OPCIONES
    paginas = {"Dispositivos": DeviceView(), "Configuración": SettingsView()}
    ventana = MainWindow(paginas)
    assert "Alertas" not in ventana.botones
    etiquetas = {w.text() for w in ventana.findChildren(type(ventana.botones["Dispositivos"]))}
    assert "Alertas" not in etiquetas
    from PySide6.QtWidgets import QLabel
    textos_estaticos = {w.text() for w in ventana.findChildren(QLabel)}
    assert "Alertas" not in textos_estaticos
    ventana.hide()


def test_seleccion_de_interfaz_se_conserva(qapp, tmp_path):
    # Primera ejecución: se guarda la Wi-Fi.
    a = App(tmp_path)
    try:
        a.config.cargar_interfaces()
        assert esperar(qapp, lambda: a.vista_cfg.combo_interfaz.isEnabled())
        indice = a.vista_cfg.combo_interfaz.findData("{GUID-WIFI}")
        a.vista_cfg.combo_interfaz.setCurrentIndex(indice)
        a.vista_cfg.combo_interfaz.activated.emit(indice)
        assert a.cfg.cargar().interfaz_id == "{GUID-WIFI}"
    finally:
        a.cerrar()
    # Segunda ejecución (nueva app, mismo directorio): el combo abre en la guardada.
    b = App(tmp_path)
    try:
        b.config.cargar_interfaces()
        assert esperar(qapp, lambda: b.vista_cfg.combo_interfaz.isEnabled())
        assert b.vista_cfg.combo_interfaz.currentData() == "{GUID-WIFI}"
    finally:
        b.cerrar()


def test_selector_muestra_todas_las_interfaces(qapp, app):
    app.config.cargar_interfaces()
    assert esperar(qapp, lambda: app.vista_cfg.combo_interfaz.isEnabled())
    combo = app.vista_cfg.combo_interfaz
    datos = {combo.itemData(i) for i in range(combo.count())}
    assert {"{GUID-WIFI}", "{GUID-ETH}"} <= datos
    # El desplegable usa una QListView estilizada (no el popup nativo).
    from PySide6.QtWidgets import QListView
    assert isinstance(combo.view(), QListView)
    assert combo.view().objectName() == "listaInterfaces"
    textos = [combo.itemText(i) for i in range(combo.count())]
    assert any("192.168" in t or "Wi-Fi" in t for t in textos)   # Info legible por opción


def test_dialogo_conserva_diseno_e_incorpora_aislar(qapp, app):
    from datetime import datetime

    from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

    from app.models.dispositivo import FuenteObservacion, PerfilDispositivo
    from presentation.views.review_dialog import ACCION_AISLAR, ACCION_AUTORIZAR, RevisarDispositivoDialog
    perfil = PerfilDispositivo(mac=MAC_PC, ip="10.0.0.14", primera_deteccion=datetime(2026, 10, 20),
                               ultima_deteccion=datetime(2026, 10, 20), fabricante="Dell Inc.",
                               hostname="PC", fuente=FuenteObservacion.RESPUESTA_ARP)
    dialogo = RevisarDispositivoDialog(perfil)
    etiquetas = {w.text() for w in dialogo.findChildren(QLabel)}
    # El diseño original conserva todos los datos del dispositivo.
    for esperado in ("Nombre de host", "Dirección IP", "Dirección MAC", "Fabricante",
                     "Detección", "Primera detección", "Alias (opcional)"):
        assert esperado in etiquetas
    assert dialogo.findChild(QLineEdit) is not None      # Campo de alias
    botones = {b.text() for b in dialogo.findChildren(QPushButton)}
    assert botones == {"Cancelar", "Aislar", "Autorizar"}   # Solo se añadió «Aislar»

    dialogo._al_aislar()
    assert dialogo.accion == ACCION_AISLAR
    otro = RevisarDispositivoDialog(perfil)
    otro._al_autorizar()
    assert otro.accion == ACCION_AUTORIZAR
