from datetime import datetime, timedelta

import pytest

from app.models.configuracion import ConfiguracionSistema, EstadoMonitoreo
from app.models.dispositivo import EstadoDispositivo, PerfilDispositivo
from app.models.dispositivo_confiable import DispositivoConfiable, OrigenRegistro, limpiar_alias
from app.models.interfaz_red import TipoInterfaz
from app.models.inventario import InventarioTemporal
from app.models.mac import (es_administrada_localmente, es_mac_de_dispositivo, es_multicast,
                            normalizar_mac)
from dobles import interfaz

T0 = datetime(2026, 10, 20, 12, 0, 0)


def perfil(mac, ip, cuando=T0):
    return PerfilDispositivo(mac=mac, ip=ip, primera_deteccion=cuando, ultima_deteccion=cuando)


@pytest.mark.parametrize("entrada", ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabb.ccdd.eeff",
                                     "AABBCCDDEEFF"])
def test_normalizar_mac(entrada):
    assert normalizar_mac(entrada) == "AA:BB:CC:DD:EE:FF"


@pytest.mark.parametrize("entrada", ["", "AA:BB:CC:DD:EE", "GG:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF:00"])
def test_mac_invalida_rechazada(entrada):
    with pytest.raises(ValueError):
        normalizar_mac(entrada)


def test_tipos_de_mac():
    assert es_multicast("01:00:5E:7F:FF:FA")
    assert not es_mac_de_dispositivo("FF:FF:FF:FF:FF:FF")
    assert not es_mac_de_dispositivo("00:00:00:00:00:00")
    assert es_mac_de_dispositivo("10:24:07:AA:E3:89")
    assert es_administrada_localmente("2E:F7:3C:6A:FB:AB")      # MAC aleatoria
    assert not es_administrada_localmente("10:24:07:AA:E3:89")


def test_interfaz_no_utilizable():
    assert interfaz().utilizable
    assert "desconectada" in interfaz(conectada=False).motivo_no_utilizable()
    assert "169.254" in interfaz(ip="169.254.10.2", prefijo=16).motivo_no_utilizable()
    assert "IPv4" in interfaz(ip=None, prefijo=None).motivo_no_utilizable()


def test_configuracion_ida_y_vuelta():
    cfg = ConfiguracionSistema("{X}", "Wi-Fi", TipoInterfaz.WIFI, EstadoMonitoreo.ACTIVO, T0)
    assert ConfiguracionSistema.desde_dict(cfg.a_dict()) == cfg
    assert ConfiguracionSistema.desde_dict({}).estado_monitoreo is EstadoMonitoreo.INACTIVO


def test_dispositivo_confiable_ida_y_vuelta():
    d = DispositivoConfiable("AA:BB:CC:00:11:22", "Laptop", T0, OrigenRegistro.ESCANEO, True)
    assert DispositivoConfiable.desde_dict(d.a_dict()) == d
    assert limpiar_alias("   ") is None
    assert limpiar_alias("  Laptop   de  trabajo ") == "Laptop de trabajo"
    with pytest.raises(ValueError):
        limpiar_alias("x" * 65)


def test_inventario_tolera_ciclos_sin_respuesta():
    inv = InventarioTemporal(ciclos_tolerancia=2)
    inv.actualizar([perfil("AA:00:00:00:00:01", "10.0.0.2")], T0)
    for i in range(1, 3):                       # 2 ciclos sin respuesta: se mantiene
        inv.actualizar([], T0 + timedelta(seconds=30 * i))
        assert len(inv) == 1
    inv.actualizar([], T0 + timedelta(seconds=90))  # 3.º ciclo: se retira
    assert len(inv) == 0


def test_inventario_conserva_primera_deteccion_y_ordena_por_ip():
    inv = InventarioTemporal()
    inv.actualizar([perfil("AA:00:00:00:00:01", "10.0.0.20")], T0)
    despues = T0 + timedelta(minutes=1)
    inv.actualizar([perfil("AA:00:00:00:00:01", "10.0.0.20", despues),
                    perfil("AA:00:00:00:00:02", "10.0.0.3", despues)], despues)
    lista = inv.visibles()
    assert [p.ip for p in lista] == ["10.0.0.3", "10.0.0.20"]
    assert lista[1].primera_deteccion == T0 and lista[1].ultima_deteccion == despues


def test_inventario_excluye_autorizados_y_aislados():
    inv = InventarioTemporal()
    inv.actualizar([perfil("AA:00:00:00:00:01", "10.0.0.2"),
                    perfil("AA:00:00:00:00:02", "10.0.0.3"),
                    perfil("AA:00:00:00:00:03", "10.0.0.4")], T0)
    # AA:...:01 autorizado, AA:...:02 aislado → solo queda AA:...:03, DESCONOCIDO.
    visibles = inv.visibles(excluidas={"AA:00:00:00:00:01", "AA:00:00:00:00:02"})
    assert [p.mac for p in visibles] == ["AA:00:00:00:00:03"]
    assert visibles[0].estado is EstadoDispositivo.DESCONOCIDO
    assert inv.macs() == {"AA:00:00:00:00:01", "AA:00:00:00:00:02", "AA:00:00:00:00:03"}
