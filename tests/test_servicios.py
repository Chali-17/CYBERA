import threading
import time
from datetime import datetime

import pytest

from app.models.dispositivo import EstadoDispositivo, FuenteObservacion
from app.models.interfaz_red import TipoInterfaz
from app.services.device_discovery_service import DeviceDiscoveryService, InterfazNoDisponibleError
from app.services.isolation_service import IsolationService
from app.services.monitoring_service import MonitoringService, TipoResultado
from app.services.network_interface_service import NetworkInterfaceService
from app.services.settings_service import ConfiguracionInvalidaError, SettingsService
from app.services.whitelist_service import DispositivoYaAutorizadoError, WhitelistService
from dobles import HostnamesFalso, OuiFalso, ProveedorInterfacesFalso, SondaFalsa, interfaz
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository

MAC_ROUTER = "10:24:07:AA:E3:89"
MAC_PC = "50:9A:4C:4C:78:B2"
MAC_ALEATORIA = "2E:F7:3C:6A:FB:AB"
MAC_PROPIA = "02:00:00:00:00:05"
T0_SRV = datetime(2026, 10, 20, 12, 0, 0)


def descubridor(sonda=None, hostnames=None, **kw):
    return DeviceDiscoveryService(
        sonda or SondaFalsa({"10.0.0.1": MAC_ROUTER, "10.0.0.14": MAC_PC,
                             "10.0.0.12": MAC_ALEATORIA, "10.0.0.5": MAC_PROPIA}),
        OuiFalso({"10:24:07": "Huawei Technologies Co.,Ltd", "50:9A:4C": "Dell Inc."}),
        hostnames or HostnamesFalso({"10.0.0.14": "DESKTOP-PRUEBA"}),
        nombre_equipo="ESTE-PC", tiempo_maximo_hostname=0.5, **kw)


# --- DeviceDiscoveryService ---------------------------------------------------

def test_descubrimiento_enriquece_sin_inventar():
    resultado = descubridor().descubrir(interfaz(), threading.Event())
    por_mac = {p.mac: p for p in resultado.perfiles}
    assert set(por_mac) == {MAC_ROUTER, MAC_PC, MAC_ALEATORIA, MAC_PROPIA}
    assert por_mac[MAC_ROUTER].fabricante == "Huawei Technologies Co.,Ltd"
    assert por_mac[MAC_ROUTER].es_puerta_enlace and por_mac[MAC_ROUTER].hostname is None
    assert por_mac[MAC_PC].hostname == "DESKTOP-PRUEBA"
    assert por_mac[MAC_ALEATORIA].fabricante is None          # MAC local: no se busca OUI
    assert por_mac[MAC_PROPIA].es_este_equipo and por_mac[MAC_PROPIA].hostname == "ESTE-PC"
    assert resultado.barrido_activo and resultado.hosts_sondeados == 254


def test_descubrimiento_descarta_difusion_y_fuera_de_subred():
    sonda = SondaFalsa(respuestas={"10.0.0.14": MAC_PC},
                       vecinos={"10.0.0.255": "FF:FF:FF:FF:FF:FF", "224.0.0.251": "01:00:5E:00:00:FB",
                                "192.168.9.9": "AA:AA:AA:00:00:01", "10.0.0.30": "AC:00:00:00:00:30"})
    perfiles = descubridor(sonda=sonda).descubrir(interfaz(mac=None), threading.Event()).perfiles
    assert {p.mac for p in perfiles} == {MAC_PC, "AC:00:00:00:00:30"}
    fuente = {p.mac: p.fuente for p in perfiles}
    assert fuente["AC:00:00:00:00:30"] is FuenteObservacion.VECINO_ALCANZABLE


def test_descubrimiento_usa_solo_la_interfaz_indicada():
    sonda = SondaFalsa({"10.0.0.14": MAC_PC})
    descubridor(sonda=sonda).descubrir(interfaz(ip="10.0.0.5"), threading.Event())
    ips, origen = sonda.sondeos[0]
    assert origen == "10.0.0.5"
    assert all(ip.startswith("10.0.0.") for ip in ips)


def test_subred_grande_no_se_barre():
    sonda = SondaFalsa(vecinos={"10.0.3.7": "AC:00:00:00:00:07"})
    resultado = descubridor(sonda=sonda).descubrir(interfaz(prefijo=16), threading.Event())
    assert sonda.sondeos == [] and not resultado.barrido_activo
    assert "AC:00:00:00:00:07" in {p.mac for p in resultado.perfiles}


def test_hostname_lento_no_bloquea_el_ciclo():
    lento = HostnamesFalso({"10.0.0.14": "TARDE"}, lentos={"10.0.0.14"}, demora=3)
    inicio = time.monotonic()
    perfiles = descubridor(hostnames=lento).descubrir(interfaz(), threading.Event()).perfiles
    assert time.monotonic() - inicio < 2.0
    assert next(p for p in perfiles if p.mac == MAC_PC).hostname is None


def test_interfaz_desconectada_no_se_escanea():
    sonda = SondaFalsa()
    with pytest.raises(InterfazNoDisponibleError):
        descubridor(sonda=sonda).descubrir(interfaz(conectada=False), threading.Event())
    assert sonda.sondeos == []


def test_cancelacion_detiene_el_descubrimiento():
    cancelar = threading.Event()
    cancelar.set()
    assert descubridor().descubrir(interfaz(), cancelar).cancelado


# --- WhitelistService / SettingsService -------------------------------------

def test_autorizar_persiste_y_rechaza_duplicados(tmp_path):
    servicio = WhitelistService(JsonWhitelistRepository(tmp_path / "lista_blanca.json"))
    registro = servicio.autorizar("50-9a-4c-4c-78-b2", "  Laptop  ")
    assert registro.mac == MAC_PC and registro.alias == "Laptop"
    assert servicio.esta_autorizado(MAC_PC)
    with pytest.raises(DispositivoYaAutorizadoError):
        servicio.autorizar(MAC_PC)
    with pytest.raises(ValueError):
        servicio.autorizar("no-es-una-mac")
    with pytest.raises(ValueError):
        servicio.autorizar("FF:FF:FF:FF:FF:FF")


def test_activar_monitoreo_requiere_interfaz(tmp_path):
    servicio = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
    with pytest.raises(ConfiguracionInvalidaError):
        servicio.activar_monitoreo()
    servicio.seleccionar_interfaz(interfaz())
    assert servicio.activar_monitoreo().monitoreo_activo
    assert not servicio.desactivar_monitoreo().monitoreo_activo


# --- MonitoringService --------------------------------------------------------

class Entorno:
    def __init__(self, tmp_path, interfaces=None, sonda=None):
        self.proveedor = ProveedorInterfacesFalso(interfaces or [interfaz()])
        self.sonda = sonda or SondaFalsa({"10.0.0.1": MAC_ROUTER, "10.0.0.14": MAC_PC})
        self.configuracion = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
        self.repo_lista_blanca = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
        self.lista_blanca = WhitelistService(self.repo_lista_blanca)
        self.repo_aislamientos = JsonIsolationRepository(tmp_path / "aislamientos.json")
        self.aislamiento = IsolationService(self.repo_aislamientos, self.repo_lista_blanca)
        self.servicio = MonitoringService(self.configuracion, NetworkInterfaceService(self.proveedor),
                                          descubridor(sonda=self.sonda), self.lista_blanca,
                                          aislamiento=self.aislamiento)

    def ciclo(self):
        return self.servicio.ejecutar_ciclo(threading.Event())


def test_monitoreo_inactivo_no_escanea(tmp_path):
    e = Entorno(tmp_path)
    e.configuracion.seleccionar_interfaz(interfaz())
    resultado = e.ciclo()
    assert resultado.tipo is TipoResultado.MONITOREO_INACTIVO and resultado.dispositivos == []
    assert e.sonda.sondeos == [] and e.proveedor.llamadas == 0


def test_monitoreo_activo_excluye_autorizados(tmp_path):
    e = Entorno(tmp_path)
    e.configuracion.seleccionar_interfaz(interfaz())
    e.configuracion.activar_monitoreo()
    e.lista_blanca.autorizar(MAC_ROUTER, "Router")           # Autorizado: no debe aparecer
    resultado = e.ciclo()
    assert resultado.tipo is TipoResultado.ACTUALIZADO
    macs = {p.mac for p in resultado.dispositivos}
    assert MAC_ROUTER not in macs                            # Excluido por lista blanca
    assert MAC_PC in macs                                    # Desconocido: sigue visible
    assert all(p.estado is EstadoDispositivo.DESCONOCIDO for p in resultado.dispositivos)


def test_monitoreo_activo_excluye_aislados(tmp_path):
    e = Entorno(tmp_path)
    e.configuracion.seleccionar_interfaz(interfaz())
    e.configuracion.activar_monitoreo()
    # Registro de aislamiento activo directo en el repositorio (fuente de verdad).
    from app.models.aislamiento import AccionAislamiento
    e.repo_aislamientos.crear(AccionAislamiento(mac_objetivo=MAC_PC, fecha_inicio=T0_SRV,
                                                autorizado_por="prueba"))
    resultado = e.ciclo()
    macs = {p.mac for p in resultado.dispositivos}
    assert MAC_PC not in macs                                # Excluido por aislamiento
    assert MAC_ROUTER in macs


def test_aislamiento_danado_no_muestra_dispositivos(tmp_path):
    e = Entorno(tmp_path)
    e.configuracion.seleccionar_interfaz(interfaz())
    e.configuracion.activar_monitoreo()
    (tmp_path / "aislamientos.json").write_text("dañado", encoding="utf-8")
    resultado = e.ciclo()
    assert resultado.tipo is TipoResultado.ERROR and resultado.dispositivos == []


def test_desactivar_y_reactivar(tmp_path):
    e = Entorno(tmp_path)
    e.configuracion.seleccionar_interfaz(interfaz())
    e.configuracion.activar_monitoreo()
    assert e.ciclo().tipo is TipoResultado.ACTUALIZADO
    e.configuracion.desactivar_monitoreo()
    sondeos = len(e.sonda.sondeos)
    assert e.ciclo().tipo is TipoResultado.MONITOREO_INACTIVO
    assert len(e.sonda.sondeos) == sondeos                     # Ningún escaneo nuevo
    assert e.servicio.reclasificar() == []                     # Inventario descartado
    e.configuracion.activar_monitoreo()
    assert e.ciclo().tipo is TipoResultado.ACTUALIZADO
    assert len(e.sonda.sondeos) == sondeos + 1


def test_interfaz_ausente_no_cambia_a_otra(tmp_path):
    otra = interfaz(id_="{GUID-ETH}", nombre="Ethernet", ip="10.1.1.5", tipo=TipoInterfaz.ETHERNET)
    e = Entorno(tmp_path, interfaces=[interfaz(), otra])
    e.configuracion.seleccionar_interfaz(interfaz())
    e.configuracion.activar_monitoreo()
    e.proveedor.interfaces = [otra]                           # La Wi-Fi desaparece
    resultado = e.ciclo()
    assert resultado.tipo is TipoResultado.INTERFAZ_NO_DISPONIBLE
    assert "Wi-Fi" in resultado.mensaje and resultado.dispositivos == []
    assert e.sonda.sondeos == []                              # No se escaneó la Ethernet


def test_interfaz_desconectada_informa_y_limpia(tmp_path):
    e = Entorno(tmp_path)
    e.configuracion.seleccionar_interfaz(interfaz())
    e.configuracion.activar_monitoreo()
    assert e.ciclo().dispositivos
    e.proveedor.interfaces = [interfaz(conectada=False)]
    resultado = e.ciclo()
    assert resultado.tipo is TipoResultado.INTERFAZ_NO_DISPONIBLE
    assert "desconectada" in resultado.mensaje
    assert e.servicio.reclasificar() == []


def test_lista_blanca_danada_no_se_presenta_como_desconocidos(tmp_path):
    e = Entorno(tmp_path)
    e.configuracion.seleccionar_interfaz(interfaz())
    e.configuracion.activar_monitoreo()
    (tmp_path / "lista_blanca.json").write_text("dañado", encoding="utf-8")
    resultado = e.ciclo()
    assert resultado.tipo is TipoResultado.ERROR and resultado.dispositivos == []
