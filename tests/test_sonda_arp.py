"""Pruebas de la consulta complementaria de vecinos (WindowsArpProbe).

Get-NetNeighbor usa un timeout PROPIO y corto, separado del timeout global de
PowerShell, para no retrasar el ciclo de descubrimiento. Si vence, lanza
PowerShellError (el servicio lo registra y continúa con el barrido ARP activo).

Se inyecta un ejecutor de PowerShell doble: no se toca la red.
"""

from __future__ import annotations

import pytest

from infrastructure.network.powershell import PowerShellError
from infrastructure.network.windows_arp import TIMEOUT_VECINOS_POR_DEFECTO, WindowsArpProbe

MAC = "50:9A:4C:4C:78:B2"


def _ejecutor_espia(respuesta=None, error=None):
    """Doble de ``ejecutar_json`` que registra el timeout con que se le llama."""
    capturado = {}

    def ejecutor(script, timeout=None):
        capturado["timeout"] = timeout
        capturado["script"] = script
        if error is not None:
            raise error
        return respuesta or []

    ejecutor.capturado = capturado
    return ejecutor


# --- Timeout propio, corto y configurable -------------------------------------

def test_usa_un_timeout_corto_separado_del_global():
    ejecutor = _ejecutor_espia([{"IP": "10.0.0.14", "Mac": MAC}])
    sonda = WindowsArpProbe(ejecutor_ps=ejecutor)
    sonda.vecinos_alcanzables(7)
    assert ejecutor.capturado["timeout"] == TIMEOUT_VECINOS_POR_DEFECTO
    assert TIMEOUT_VECINOS_POR_DEFECTO < 30          # No es el timeout global de 30 s.


def test_el_timeout_es_configurable():
    ejecutor = _ejecutor_espia([])
    WindowsArpProbe(ejecutor_ps=ejecutor, timeout_vecinos=2.0).vecinos_alcanzables(7)
    assert ejecutor.capturado["timeout"] == 2.0


# --- Respuesta rápida ----------------------------------------------------------

def test_respuesta_rapida_devuelve_observaciones():
    ejecutor = _ejecutor_espia([{"IP": "10.0.0.14", "Mac": MAC},
                                {"IP": "10.0.0.1", "Mac": "no-es-mac"}])
    obs = WindowsArpProbe(ejecutor_ps=ejecutor).vecinos_alcanzables(7)
    # Solo el registro con MAC válida; el inválido se descarta (no se inventa nada).
    assert {o.ip for o in obs} == {"10.0.0.14"}
    assert {o.mac for o in obs} == {MAC}


# --- Timeout: PowerShellError ---------------------------------------------------

def test_timeout_lanza_powershellerror():
    ejecutor = _ejecutor_espia(error=PowerShellError("PowerShell no respondió a tiempo."))
    with pytest.raises(PowerShellError):
        WindowsArpProbe(ejecutor_ps=ejecutor).vecinos_alcanzables(7)
    assert ejecutor.capturado["timeout"] == TIMEOUT_VECINOS_POR_DEFECTO


# --- Errores no recuperables se propagan ---------------------------------------

def test_error_no_recuperable_se_propaga():
    ejecutor = _ejecutor_espia(error=RuntimeError("fallo inesperado"))
    with pytest.raises(RuntimeError):
        WindowsArpProbe(ejecutor_ps=ejecutor).vecinos_alcanzables(7)
