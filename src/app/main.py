"""Punto de composición: crea repositorios, servicios, controladores y vistas."""

from __future__ import annotations

import logging
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from app.controllers.device_controller import DeviceController
from app.controllers.monitoring_controller import MonitoringController
from app.controllers.settings_controller import SettingsController
from app.services.device_discovery_service import DeviceDiscoveryService
from app.services.isolation_service import IsolationService
from app.services.monitoring_service import MonitoringService
from app.services.network_interface_service import NetworkInterfaceService
from app.services.settings_service import SettingsService
from app.services.whitelist_service import WhitelistService
from infrastructure.network.hostname_resolver import SocketHostnameResolver
from infrastructure.network.oui_resolver import WiresharkManufResolver
from infrastructure.network.windows_arp import WindowsArpProbe
from infrastructure.network.windows_interfaces import WindowsNetworkInterfaceProvider
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.persistence.rutas import (ARCHIVO_AISLAMIENTOS, ARCHIVO_CONFIGURACION,
                                              ARCHIVO_LISTA_BLANCA, directorio_datos)
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository
from presentation.estilos import HOJA_ESTILOS
from presentation.views.device_view import DeviceView
from presentation.views.main_window import MainWindow
from presentation.views.settings_view import SettingsView

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
RUTA_OUI = RAIZ_PROYECTO / "recursos" / "oui" / "manuf"


@dataclass
class Aplicacion:
    ventana: MainWindow
    monitoreo: MonitoringController
    configuracion: SettingsController
    dispositivos: DeviceController


def construir(directorio: Path | None = None) -> Aplicacion:
    directorio = directorio or directorio_datos()
    # Persistencia: configuración, lista blanca y aislamientos. El inventario
    # de dispositivos detectados NO se guarda (es temporal, en memoria).
    repo_configuracion = JsonSettingsRepository(directorio / ARCHIVO_CONFIGURACION)
    repo_lista_blanca = JsonWhitelistRepository(directorio / ARCHIVO_LISTA_BLANCA)
    repo_aislamientos = JsonIsolationRepository(directorio / ARCHIVO_AISLAMIENTOS)

    servicio_configuracion = SettingsService(repo_configuracion)
    servicio_lista_blanca = WhitelistService(repo_lista_blanca)
    # Motor de red de Capa 2 aún no implementado (módulo de defensa activa):
    # motor=None hace que el aislamiento informe «no disponible» sin simularlo.
    servicio_aislamiento = IsolationService(repo_aislamientos, repo_lista_blanca, motor=None)
    servicio_interfaces = NetworkInterfaceService(WindowsNetworkInterfaceProvider())
    servicio_descubrimiento = DeviceDiscoveryService(
        sonda=WindowsArpProbe(),
        oui=WiresharkManufResolver(RUTA_OUI),
        hostnames=SocketHostnameResolver(),
        nombre_equipo=socket.gethostname() or None,
    )
    servicio_monitoreo = MonitoringService(servicio_configuracion, servicio_interfaces,
                                           servicio_descubrimiento, servicio_lista_blanca,
                                           aislamiento=servicio_aislamiento)

    vista_dispositivos = DeviceView()
    vista_configuracion = SettingsView()
    ventana = MainWindow({"Dispositivos": vista_dispositivos,
                          "Configuración": vista_configuracion})

    monitoreo = MonitoringController(servicio_monitoreo, servicio_configuracion, parent=ventana)
    dispositivos = DeviceController(vista_dispositivos, monitoreo, servicio_monitoreo,
                                    servicio_lista_blanca, servicio_aislamiento, parent=ventana)
    configuracion = SettingsController(vista_configuracion, servicio_configuracion,
                                       servicio_interfaces, parent=ventana)
    monitoreo.indicadorCambiado.connect(ventana.set_indicador)
    configuracion.configuracionCambiada.connect(monitoreo.reevaluar)
    return Aplicacion(ventana, monitoreo, configuracion, dispositivos)


def main() -> int:
    # Registro solo en consola: nunca se escriben los dispositivos detectados en disco.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("CYBERA")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(HOJA_ESTILOS)
    if sys.platform != "win32":
        QMessageBox.critical(None, "CYBERA", "CYBERA requiere Windows 10 u 11 (RNF01).")
        return 1
    if not RUTA_OUI.is_file():
        logging.warning("No se encontró %s; el fabricante se mostrará como «No disponible».",
                        RUTA_OUI)

    aplicacion = construir()
    pantalla = QGuiApplication.primaryScreen().availableGeometry()
    aplicacion.ventana.resize(min(1440, pantalla.width()), min(900, pantalla.height()))
    aplicacion.ventana.show()
    aplicacion.monitoreo.iniciar()

    def al_salir() -> None:
        aplicacion.monitoreo.detener()       # Cancela el ciclo y descarta el inventario.
        aplicacion.configuracion.detener()

    app.aboutToQuit.connect(al_salir)
    return app.exec()
