"""Consulta del fabricante en el archivo manuf incluido (datos del registro IEEE)."""

from pathlib import Path

import pytest

from infrastructure.network.oui_resolver import WiresharkManufResolver

RUTA = Path(__file__).resolve().parents[1] / "recursos" / "oui" / "manuf"
pytestmark = pytest.mark.skipif(not RUTA.is_file(), reason="Falta recursos/oui/manuf")


@pytest.fixture(scope="module")
def oui():
    return WiresharkManufResolver(RUTA)


def test_bloque_ma_l_24_bits(oui):
    assert oui.fabricante("50:9A:4C:00:00:01") == "Dell Inc."


def test_bloque_ma_s_36_bits_tiene_prioridad(oui):
    # 00:1B:C5:00:0x pertenece a un bloque MA-S de 36 bits dentro del OUI 00:1B:C5.
    assert oui.fabricante("00:1B:C5:00:00:11") == "Converging Systems Inc."


def test_prefijo_sin_registro_devuelve_none(oui):
    assert oui.fabricante("02:12:34:56:78:9A") is None
