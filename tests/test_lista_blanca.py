"""Pruebas del módulo Lista blanca (Mockup 04).

- Unitarias/persistencia: repositorio y servicio (sin Qt, sin red).
- Integración MVC: vista + controlador con Qt offscreen y servicios reales
  (repositorios de archivos), sin tráfico de red.
"""

import json
from datetime import datetime

import pytest

from app.models.aislamiento import AccionAislamiento
from app.models.dispositivo import FuenteObservacion, PerfilDispositivo
from app.models.dispositivo_confiable import DispositivoConfiable, OrigenRegistro
from app.services.isolation_service import IsolationService
from app.services.monitoring_service import MonitoringService
from app.services.network_interface_service import NetworkInterfaceService
from app.services.settings_service import SettingsService
from app.services.whitelist_service import WhitelistService
from dobles import OuiFalso, ProveedorInterfacesFalso, SondaFalsa, interfaz
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository
from app.services.device_discovery_service import DeviceDiscoveryService
from dobles import HostnamesFalso

T0 = datetime(2026, 10, 20, 12, 0, 0)
MAC_A = "A4:5E:60:21:7C:91"
MAC_B = "90:9F:33:12:AB:20"


def _confiable(mac=MAC_A, alias="Laptop", fecha=T0, activo=True):
    return DispositivoConfiable(mac, alias, fecha, OrigenRegistro.ESCANEO, activo)


# --- Repositorio y servicio (unitarias/persistencia) -------------------------

def test_repo_actualizar_alias_conserva_identidad(tmp_path):
    ruta = tmp_path / "lista_blanca.json"
    repo = JsonWhitelistRepository(ruta)
    repo.add(_confiable())
    actualizado = repo.actualizar_alias("a4-5e-60-21-7c-91", "Equipo de oficina")
    assert actualizado.alias == "Equipo de oficina"
    assert actualizado.mac == MAC_A                      # Identidad intacta
    assert actualizado.fecha_autorizacion == T0
    assert actualizado.origen_registro is OrigenRegistro.ESCANEO
    # No se duplica: sigue habiendo un solo registro, leído de disco.
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert len(datos["dispositivos"]) == 1
    assert datos["dispositivos"][0]["alias"] == "Equipo de oficina"


def test_repo_actualizar_alias_inexistente(tmp_path):
    repo = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
    with pytest.raises(ValueError):
        repo.actualizar_alias(MAC_A, "x")


def test_service_listar_filtra_y_ordena(tmp_path):
    repo = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
    repo.add(_confiable(MAC_A, "A", datetime(2026, 9, 1)))
    repo.add(_confiable(MAC_B, "B", datetime(2026, 9, 28)))
    servicio = WhitelistService(repo)
    listado = servicio.listar()
    assert [d.mac for d in listado] == [MAC_B, MAC_A]     # Más reciente primero
    assert servicio.buscar(MAC_A).alias == "A"
    assert servicio.buscar("00:00:00:00:00:11") is None


def test_service_editar_alias_persiste_y_no_duplica(tmp_path):
    ruta = tmp_path / "lista_blanca.json"
    servicio = WhitelistService(JsonWhitelistRepository(ruta))
    servicio.autorizar(MAC_A, "Original")
    servicio.editar_alias(MAC_A, "  Nuevo alias ")
    # Nueva instancia (releída de disco): el cambio persiste y no hay duplicados.
    recargado = WhitelistService(JsonWhitelistRepository(ruta))
    assert recargado.buscar(MAC_A).alias == "Nuevo alias"
    assert len(recargado.listar()) == 1


def test_service_editar_alias_vacio_queda_sin_alias(tmp_path):
    servicio = WhitelistService(JsonWhitelistRepository(tmp_path / "lista_blanca.json"))
    servicio.autorizar(MAC_A, "Algo")
    servicio.editar_alias(MAC_A, "   ")
    assert servicio.buscar(MAC_A).alias is None


def test_service_retirar(tmp_path):
    servicio = WhitelistService(JsonWhitelistRepository(tmp_path / "lista_blanca.json"))
    servicio.autorizar(MAC_A, "X")
    servicio.retirar(MAC_A)
    assert servicio.buscar(MAC_A) is None
    assert servicio.listar() == []


# --- Integración MVC (Qt offscreen) ------------------------------------------

class Harness:
    def __init__(self, tmp_path):
        from app.controllers.whitelist_controller import WhitelistController
        from presentation.views.whitelist_view import WhitelistView
        self.dir = tmp_path
        self.repo_lb = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
        self.lb = WhitelistService(self.repo_lb)
        self.repo_ais = JsonIsolationRepository(tmp_path / "aislamientos.json")
        self.aislamiento = IsolationService(self.repo_ais, self.repo_lb, motor=None)
        cfg = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
        interfaces = NetworkInterfaceService(ProveedorInterfacesFalso([interfaz()]))
        descubrimiento = DeviceDiscoveryService(SondaFalsa(), OuiFalso(), HostnamesFalso(),
                                                tiempo_maximo_hostname=0.1)
        self.monitoreo = MonitoringService(cfg, interfaces, descubrimiento, self.lb,
                                           aislamiento=self.aislamiento)
        self.vista = WhitelistView()
        self.navego = []
        self.ctrl = WhitelistController(self.vista, self.lb, self.monitoreo, self.aislamiento)
        self.ctrl.irADispositivos.connect(lambda: self.navego.append(True))

    def macs_en_tabla(self):
        t = self.vista._tabla
        return {t.item(f, 1).text() for f in range(t.rowCount())}


@pytest.fixture
def h(qapp, tmp_path):
    return Harness(tmp_path)


def test_tabla_carga_registros_reales_y_estructura(h):
    h.repo_lb.add(_confiable(MAC_A, "Laptop de trabajo", datetime(2026, 9, 28)))
    h.repo_lb.add(_confiable(MAC_B, None, datetime(2026, 9, 27)))
    h.ctrl.recargar()
    assert h.vista.filas == 2
    assert h.macs_en_tabla() == {MAC_A, MAC_B}
    tabla = h.vista._tabla
    assert tabla.columnCount() == 5
    cabeceras = [tabla.horizontalHeaderItem(i).text() for i in range(5)]
    assert cabeceras == ["Alias", "MAC", "Fecha", "Estado", "Acción"]
    # Fila sin alias muestra «Sin alias»; fecha formateada.
    fila_b = next(f for f in range(tabla.rowCount()) if tabla.item(f, 1).text() == MAC_B)
    assert tabla.item(fila_b, 0).text() == "Sin alias"
    assert tabla.item(fila_b, 2).text() == "27/09/2026"


def test_solo_boton_agregar_y_navega(h):
    assert h.vista.boton_agregar.text() == "Agregar"
    h.vista.boton_agregar.click()
    assert h.navego == [True]           # «Agregar» navega a Dispositivos


def test_autorizacion_externa_se_refleja_al_recargar(h):
    h.ctrl.recargar()
    assert h.vista.filas == 0
    # Simula autorización hecha desde Dispositivos (mismo servicio/repositorio).
    h.lb.autorizar(MAC_A, "Nuevo")
    h.vista.mostrada.emit()            # Al volver a Lista blanca se recarga.
    assert MAC_A in h.macs_en_tabla()


def test_editar_guarda_alias_y_persiste(h, monkeypatch):
    from presentation.views.edit_whitelist_dialog import ACCION_GUARDAR
    h.lb.autorizar(MAC_A, "Viejo")
    h.ctrl.recargar()
    monkeypatch.setattr(h.vista, "solicitar_edicion", lambda datos: (ACCION_GUARDAR, "Nuevo alias"))
    monkeypatch.setattr(h.vista, "informar", lambda *a: None)
    h.vista.editarSolicitado.emit(MAC_A)
    assert h.lb.buscar(MAC_A).alias == "Nuevo alias"
    # Persistido en disco (nueva instancia) y sin duplicar.
    recargado = WhitelistService(JsonWhitelistRepository(h.dir / "lista_blanca.json"))
    assert recargado.buscar(MAC_A).alias == "Nuevo alias"
    assert len(recargado.listar()) == 1
    tabla = h.vista._tabla
    assert tabla.item(0, 0).text() == "Nuevo alias"


def test_editar_cancelar_descarta_cambios(h, monkeypatch):
    h.lb.autorizar(MAC_A, "Viejo")
    h.ctrl.recargar()
    monkeypatch.setattr(h.vista, "solicitar_edicion", lambda datos: (None, "Ignorar"))
    h.vista.editarSolicitado.emit(MAC_A)
    assert h.lb.buscar(MAC_A).alias == "Viejo"


def test_editar_usa_datos_en_vivo_si_el_equipo_esta_detectado(h, monkeypatch):
    h.lb.autorizar(MAC_A, "PC")
    h.ctrl.recargar()
    perfil = PerfilDispositivo(mac=MAC_A, ip="10.0.0.9", primera_deteccion=T0, ultima_deteccion=T0,
                               fabricante="Dell Inc.", hostname="PC-OFICINA",
                               fuente=FuenteObservacion.RESPUESTA_ARP)
    monkeypatch.setattr(h.monitoreo, "perfil_detectado", lambda mac: perfil)
    capturado = {}
    monkeypatch.setattr(h.vista, "solicitar_edicion",
                        lambda datos: (capturado.update(vars(datos)), (None, None))[1])
    h.vista.editarSolicitado.emit(MAC_A)
    assert capturado["ip"] == "10.0.0.9"
    assert capturado["fabricante"] == "Dell Inc."
    assert capturado["hostname"] == "PC-OFICINA"


def test_eliminar_requiere_confirmacion(h, monkeypatch):
    h.lb.autorizar(MAC_A, "X")
    h.ctrl.recargar()
    from presentation.views.edit_whitelist_dialog import ACCION_ELIMINAR
    monkeypatch.setattr(h.vista, "solicitar_edicion", lambda datos: (ACCION_ELIMINAR, None))
    monkeypatch.setattr(h.vista, "confirmar_eliminacion", lambda alias, mac: False)  # Cancela
    h.vista.editarSolicitado.emit(MAC_A)
    assert h.lb.buscar(MAC_A) is not None      # No se eliminó
    assert MAC_A in h.macs_en_tabla()


def test_eliminar_confirmado_retira_de_la_tabla(h, monkeypatch):
    h.lb.autorizar(MAC_A, "X")
    h.ctrl.recargar()
    from presentation.views.edit_whitelist_dialog import ACCION_ELIMINAR
    monkeypatch.setattr(h.vista, "solicitar_edicion", lambda datos: (ACCION_ELIMINAR, None))
    monkeypatch.setattr(h.vista, "confirmar_eliminacion", lambda alias, mac: True)
    monkeypatch.setattr(h.vista, "informar", lambda *a: None)
    h.vista.editarSolicitado.emit(MAC_A)
    assert h.lb.buscar(MAC_A) is None
    assert MAC_A not in h.macs_en_tabla()


def test_eliminar_fallido_conserva_el_registro(h, monkeypatch):
    h.lb.autorizar(MAC_A, "X")
    h.ctrl.recargar()
    from presentation.views.edit_whitelist_dialog import ACCION_ELIMINAR
    monkeypatch.setattr(h.vista, "solicitar_edicion", lambda datos: (ACCION_ELIMINAR, None))
    monkeypatch.setattr(h.vista, "confirmar_eliminacion", lambda alias, mac: True)

    def falla(mac):
        raise OSError("disco protegido")
    monkeypatch.setattr(h.lb, "retirar", falla)
    avisos = []
    monkeypatch.setattr(h.vista, "advertir", lambda t, m: avisos.append(m))
    h.vista.editarSolicitado.emit(MAC_A)
    assert MAC_A in h.macs_en_tabla()          # Conserva el registro visible
    assert avisos


def test_eliminar_autorizacion_no_borra_aislamiento(h, monkeypatch):
    # Estados independientes: inyectamos un aislamiento activo para la misma MAC.
    h.lb.autorizar(MAC_A, "X")
    h.repo_ais.crear(AccionAislamiento(mac_objetivo=MAC_A, fecha_inicio=T0, autorizado_por="u"))
    h.ctrl.recargar()
    from presentation.views.edit_whitelist_dialog import ACCION_ELIMINAR
    monkeypatch.setattr(h.vista, "solicitar_edicion", lambda datos: (ACCION_ELIMINAR, None))
    monkeypatch.setattr(h.vista, "confirmar_eliminacion", lambda alias, mac: True)
    monkeypatch.setattr(h.vista, "informar", lambda *a: None)
    h.vista.editarSolicitado.emit(MAC_A)
    assert h.lb.buscar(MAC_A) is None                  # Autorización eliminada
    assert h.repo_ais.macs_activas() == {MAC_A}        # Aislamiento intacto


def test_aislar_sin_motor_no_marca_aislado(h, monkeypatch):
    # Un dispositivo en lista blanca no puede aislarse: motor ausente y, además,
    # RI-05 (protegido por estar autorizado). En ningún caso se marca aislado.
    h.lb.autorizar(MAC_A, "X")
    h.ctrl.recargar()
    from presentation.views.edit_whitelist_dialog import ACCION_AISLAR
    monkeypatch.setattr(h.vista, "solicitar_edicion", lambda datos: (ACCION_AISLAR, None))
    monkeypatch.setattr(h.vista, "confirmar_aislamiento", lambda alias, mac, ip: True)
    avisos = []
    monkeypatch.setattr(h.vista, "advertir", lambda t, m: avisos.append(m))
    h.vista.editarSolicitado.emit(MAC_A)
    assert h.repo_ais.macs_activas() == set()          # No se marcó como aislado
    assert avisos


def test_inventario_no_se_persiste_desde_lista_blanca(h):
    h.lb.autorizar(MAC_A, "X")
    h.ctrl.recargar()
    h.vista.editarSolicitado  # no-op
    archivos = sorted(p.name for p in h.dir.iterdir())
    assert "dispositivos.json" not in archivos
    assert archivos == ["lista_blanca.json"]
