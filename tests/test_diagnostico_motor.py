"""Pruebas del diagnóstico de red del motor (solo lectura).

Las comprobaciones unitarias no requieren privilegios, Npcap ni captura en vivo.
La observación PASIVA real está desactivada salvo que se defina
``CYBERA_PRUEBA_RED=1`` (igual que ``test_red_real``), porque abre una captura.
Nada de esto habilita el aislamiento.
"""

from __future__ import annotations

import os

import pytest

from infrastructure.network.diagnostico_motor import (CapacidadCaptura, DiagnosticoMotor,
                                                      EstadoNpcap, ObservacionTrafico,
                                                      capacidad_captura, ejecutar, estado_npcap,
                                                      observar_trafico, tiene_privilegios_admin)


def test_privilegios_devuelve_bool():
    assert isinstance(tiene_privilegios_admin(), bool)


def test_estado_npcap_estructura():
    estado = estado_npcap()
    assert isinstance(estado, EstadoNpcap)
    assert isinstance(estado.instalado, bool) and isinstance(estado.operativo, bool)
    assert estado.detalle                        # Siempre explica el resultado.


def test_capacidad_captura_estructura():
    cap = capacidad_captura()
    assert isinstance(cap, CapacidadCaptura)
    assert isinstance(cap.backend_disponible, bool) and cap.detalle


def test_observacion_trafico_ajeno():
    # Construida a mano (sin capturar): solo se afirma «ajeno» si hubo unicast de terceros.
    assert not ObservacionTrafico(segundos=1).observa_trafico_ajeno
    assert not ObservacionTrafico(segundos=1, unicast_propio=500, difusion=9).observa_trafico_ajeno
    assert ObservacionTrafico(segundos=1, unicast_ajeno=1).observa_trafico_ajeno


def test_ejecutar_no_captura_por_defecto():
    d = ejecutar()                               # Sin segundos: no abre captura.
    assert isinstance(d, DiagnosticoMotor)
    assert d.observacion is None
    assert d.adaptador is None or isinstance(d.adaptador, str)
    # El «mecanismo» depende del entorno (admin + Npcap + interfaz); solo
    # comprobamos que es un bool coherente con esos requisitos.
    assert d.hay_mecanismo_de_contencion == (
        d.admin and d.npcap.operativo and d.adaptador is not None)


def test_el_diagnostico_no_habilita_el_aislamiento(tmp_path):
    # El motor sigue no disponible pase lo que pase en el diagnóstico.
    from infrastructure.network.windows_isolation import WindowsIsolationEngine
    assert WindowsIsolationEngine().disponible() is False


@pytest.mark.skipif(os.environ.get("CYBERA_PRUEBA_RED") != "1",
                    reason="Observación de red real desactivada (defina CYBERA_PRUEBA_RED=1).")
def test_observacion_pasiva_real():
    from infrastructure.network.windows_interfaces import WindowsNetworkInterfaceProvider
    activa = next((i for i in WindowsNetworkInterfaceProvider().list_interfaces()
                   if i.conectada and i.ipv4), None)
    assert activa is not None, "No hay interfaz conectada con IPv4."
    obs = observar_trafico(activa.ipv4, segundos=4.0)
    assert obs.error is None, obs.error
    # En una red conmutada normal NO debería verse unicast de terceros.
    print(f"\nObservación real: {obs.total} paquetes, unicast ajeno {obs.unicast_ajeno}, "
          f"tipos {obs.tipos}")
