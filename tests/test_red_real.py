"""Prueba con la RED REAL del equipo (opcional).

Se ejecuta solo si se define CYBERA_PRUEBA_RED=1:
    set CYBERA_PRUEBA_RED=1  &&  python -m pytest tests/test_red_real.py -v -s
Envía solicitudes ARP a la subred de la primera interfaz física conectada.
"""

import os
import socket
import sys
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("CYBERA_PRUEBA_RED") != "1",
    reason="Prueba de red real desactivada (defina CYBERA_PRUEBA_RED=1).")

RUTA_OUI = Path(__file__).resolve().parents[1] / "recursos" / "oui" / "manuf"


def test_descubrimiento_real():
    from app.services.device_discovery_service import DeviceDiscoveryService
    from infrastructure.network.hostname_resolver import SocketHostnameResolver
    from infrastructure.network.oui_resolver import WiresharkManufResolver
    from infrastructure.network.windows_arp import WindowsArpProbe
    from infrastructure.network.windows_interfaces import WindowsNetworkInterfaceProvider

    interfaces = WindowsNetworkInterfaceProvider().list_interfaces()
    assert interfaces, "Windows no devolvió interfaces"
    candidatas = [i for i in interfaces if i.utilizable and not i.virtual]
    if not candidatas:
        pytest.skip("No hay una interfaz física conectada con IPv4")
    interfaz = candidatas[0]

    servicio = DeviceDiscoveryService(WindowsArpProbe(), WiresharkManufResolver(RUTA_OUI),
                                      SocketHostnameResolver(), nombre_equipo=socket.gethostname())
    resultado = servicio.descubrir(interfaz, threading.Event())
    print(f"\nInterfaz: {interfaz.nombre} {interfaz.ipv4}/{interfaz.prefijo}  "
          f"sondeados: {resultado.hosts_sondeados}  encontrados: {len(resultado.perfiles)}")
    for p in sorted(resultado.perfiles, key=lambda p: socket.inet_aton(p.ip)):
        print(f"  {p.ip:<15} {p.mac}  {p.fabricante or '-':<40} {p.hostname or '-'}  [{p.fuente.name}]")

    propios = [p for p in resultado.perfiles if p.es_este_equipo]
    assert len(propios) == 1 and propios[0].mac == interfaz.mac
    red = interfaz.red
    assert all(__import__("ipaddress").ip_address(p.ip) in red for p in resultado.perfiles)
    if interfaz.puerta_enlace:
        assert any(p.es_puerta_enlace for p in resultado.perfiles), "La puerta de enlace no respondió"
