import json
from datetime import datetime

import pytest

from app.models.configuracion import ConfiguracionSistema, EstadoMonitoreo
from app.models.dispositivo_confiable import DispositivoConfiable, OrigenRegistro
from app.models.interfaz_red import TipoInterfaz
from infrastructure.persistence.json_file import ArchivoDatosError
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository

T0 = datetime(2026, 10, 20, 12, 0, 0)


def confiable(mac="AA:BB:CC:00:11:22", alias="Laptop"):
    return DispositivoConfiable(mac, alias, T0, OrigenRegistro.ESCANEO, True)


def test_lista_blanca_agrega_y_persiste(tmp_path):
    ruta = tmp_path / "lista_blanca.json"
    repo = JsonWhitelistRepository(ruta)
    assert repo.list() == []
    repo.add(confiable())
    assert JsonWhitelistRepository(ruta).exists("aa-bb-cc-00-11-22")   # Nueva instancia: leído de disco
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["dispositivos"][0] == {"mac": "AA:BB:CC:00:11:22", "alias": "Laptop",
                                        "fechaAutorizacion": "2026-10-20T12:00:00",
                                        "origenRegistro": "ESCANEO", "activo": True}
    assert not list(tmp_path.glob("*.tmp"))


def test_lista_blanca_rechaza_duplicado_activo(tmp_path):
    repo = JsonWhitelistRepository(tmp_path / "lista_blanca.json")
    repo.add(confiable())
    with pytest.raises(ValueError):
        repo.add(confiable(alias="Otro"))


def test_lista_blanca_danada_no_se_sobrescribe(tmp_path):
    ruta = tmp_path / "lista_blanca.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")
    repo = JsonWhitelistRepository(ruta)
    with pytest.raises(ArchivoDatosError):
        repo.list()
    with pytest.raises(ArchivoDatosError):
        repo.add(confiable())
    assert ruta.read_text(encoding="utf-8") == "{ esto no es json"


def test_configuracion_por_defecto_e_ida_y_vuelta(tmp_path):
    repo = JsonSettingsRepository(tmp_path / "configuracion.json")
    assert repo.load() == ConfiguracionSistema()
    cfg = ConfiguracionSistema("{X}", "Wi-Fi", TipoInterfaz.WIFI, EstadoMonitoreo.ACTIVO, T0)
    repo.save(cfg)
    assert JsonSettingsRepository(tmp_path / "configuracion.json").load() == cfg


def test_configuracion_invalida_informa_error(tmp_path):
    ruta = tmp_path / "configuracion.json"
    ruta.write_text(json.dumps({"estadoMonitoreo": "QUIZAS"}), encoding="utf-8")
    with pytest.raises(ArchivoDatosError):
        JsonSettingsRepository(ruta).load()
