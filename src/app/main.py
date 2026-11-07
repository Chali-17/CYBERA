"""Punto de composición: crea repositorios, servicios, controladores y vistas."""

from __future__ import annotations

import logging
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from app.controllers.bitacora_controller import BitacoraController
from app.controllers.device_controller import DeviceController
from app.controllers.ejecutor_aislamiento import EjecutorAislamiento
from app.controllers.isolation_controller import IsolationController
from app.controllers.monitoring_controller import MonitoringController
from app.controllers.notificacion_controller import NotificacionController
from app.controllers.reporte_controller import ReporteController
from app.controllers.resumen_controller import ResumenController
from app.controllers.settings_controller import SettingsController
from app.controllers.whitelist_controller import WhitelistController
from app.services.bitacora_service import BitacoraService
from app.services.device_discovery_service import DeviceDiscoveryService
from app.services.isolation_service import IsolationService
from app.services.monitoring_service import MonitoringService
from app.services.network_interface_service import NetworkInterfaceService
from app.services.notificacion_service import NotificacionService
from app.services.reporte_service import ReporteService
from app.services.reservas_mac import coordinador_para
from app.services.settings_service import SettingsService
from app.services.whitelist_service import WhitelistService
from infrastructure.compatibilidad_datos import problema_carpeta_datos
from infrastructure.instancia_unica import InstanciaUnica, ResultadoBloqueo
from infrastructure.network.hostname_resolver import SocketHostnameResolver
from infrastructure.network.motor_aislamiento import crear_motor
from infrastructure.network.oui_resolver import WiresharkManufResolver
from infrastructure.network.windows_arp import WindowsArpProbe
from infrastructure.network.windows_interfaces import WindowsNetworkInterfaceProvider
from infrastructure.persistence.bitacora_repository import JsonBitacoraRepository
from infrastructure.persistence.isolation_repository import JsonIsolationRepository
from infrastructure.correo.smtp_gmail import EnviadorGmail
from infrastructure.persistence.notificaciones_repository import JsonNotificacionesRepository
from infrastructure.persistence.rutas import (ARCHIVO_AISLAMIENTOS, ARCHIVO_BITACORA, ARCHIVO_CONFIGURACION,
                                              ARCHIVO_LISTA_BLANCA, ARCHIVO_NOTIFICACIONES, CARPETA_REPORTES,
                                              directorio_datos)
from infrastructure.secretos import AlmacenKeyring
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository
from presentation.estilos import HOJA_ESTILOS
from presentation.views.ayuda_view import AyudaView
from presentation.views.bitacora_view import BitacoraView
from presentation.views.device_view import DeviceView
from presentation.views.isolation_view import IsolationView
from presentation.views.main_window import MainWindow
from presentation.views.reporte_view import ReporteView
from presentation.views.resumen_view import ResumenView
from presentation.views.settings_view import SettingsView
from presentation.views.whitelist_view import WhitelistView

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
RUTA_OUI = RAIZ_PROYECTO / "recursos" / "oui" / "manuf"
# Manuales que se muestran en «Ayuda» (se leen en su ubicación actual).
CARPETA_MANUALES = RAIZ_PROYECTO / "MANUEALES"
MANUALES = {"Manual de usuario": CARPETA_MANUALES / "MANUAL DE USUARIO.pdf",
            "Manual técnico de instalación": CARPETA_MANUALES / "MANUAL TECNICO DE INSTALACION.pdf"}


@dataclass
class Aplicacion:
    ventana: MainWindow
    monitoreo: MonitoringController
    configuracion: SettingsController
    dispositivos: DeviceController
    lista_blanca: WhitelistController
    servicio_aislamiento: IsolationService | None = None
    servicio_lista_blanca: WhitelistService | None = None
    aislamiento: IsolationController | None = None
    ejecutor: EjecutorAislamiento | None = None
    bitacora: BitacoraController | None = None
    reporte: ReporteController | None = None
    servicio_notificaciones: NotificacionService | None = None
    notificaciones: NotificacionController | None = None
    resumen: ResumenController | None = None


def construir(directorio: Path | None = None) -> Aplicacion:
    directorio = directorio or directorio_datos()
    # Persistencia: configuración, lista blanca y aislamientos. El inventario
    # de dispositivos detectados NO se guarda (es temporal, en memoria).
    repo_configuracion = JsonSettingsRepository(directorio / ARCHIVO_CONFIGURACION)
    repo_lista_blanca = JsonWhitelistRepository(directorio / ARCHIVO_LISTA_BLANCA)
    repo_aislamientos = JsonIsolationRepository(directorio / ARCHIVO_AISLAMIENTOS)
    repo_bitacora = JsonBitacoraRepository(directorio / ARCHIVO_BITACORA)

    servicio_configuracion = SettingsService(repo_configuracion)
    # Una sola reserva por MAC para autorizar y aislar (corrección H1).
    # Coordinador único por MAC de esta carpeta de datos: lo comparten TODOS los
    # servicios del proceso (L1); es el mismo que obtendría cualquier otro
    # IsolationService o WhitelistService construido sobre estos archivos.
    reservas = coordinador_para(directorio)
    servicio_lista_blanca = WhitelistService(repo_lista_blanca, reservas=reservas)
    servicio_bitacora = BitacoraService(repo_bitacora)
    servicio_reportes = ReporteService(servicio_bitacora, directorio=directorio / CARPETA_REPORTES)
    # Motor de red de Capa 2 (módulo de defensa activa). Por defecto es el motor
    # real para Windows, que —honestamente— se declara NO DISPONIBLE: sin control
    # del router o del conmutador no hay contención selectiva fiable y recuperable
    # (ver infrastructure/network/windows_isolation.py y el informe). La app se
    # comporta igual que con motor=None, pero con el contrato integrado de verdad.
    servicio_aislamiento = IsolationService(repo_aislamientos, repo_lista_blanca,
                                            motor=crear_motor(), reservas=reservas,
                                            bitacora=servicio_bitacora)
    try:
        # Solicitudes que quedaron sin verificar en una ejecución anterior → UNCERTAIN
        # (requieren recuperación). No se reintenta nada.
        servicio_aislamiento.recuperar_interrumpidas()
        # Las contenciones registradas quedan «sin verificar» hasta que el motor
        # las compruebe. Con un motor no disponible no se consulta nada.
        servicio_aislamiento.verificar_registrados()
    except Exception:  # noqa: BLE001 - un archivo dañado se informa al usarlo
        logging.getLogger(__name__).exception("No se pudo revisar aislamientos.json")
    servicio_interfaces = NetworkInterfaceService(WindowsNetworkInterfaceProvider())
    servicio_descubrimiento = DeviceDiscoveryService(
        sonda=WindowsArpProbe(),
        oui=WiresharkManufResolver(RUTA_OUI),
        hostnames=SocketHostnameResolver(),
        nombre_equipo=socket.gethostname() or None,
    )
    # Notificaciones por correo (Gmail SMTP). El remitente se guarda en
    # notificaciones.json; la contraseña de aplicación, solo en el Administrador de
    # credenciales de Windows. Si no está configurado, el monitoreo sigue igual.
    repo_notificaciones = JsonNotificacionesRepository(directorio / ARCHIVO_NOTIFICACIONES)
    servicio_notificaciones = NotificacionService(repo_notificaciones, AlmacenKeyring(),
                                                  enviador=EnviadorGmail())
    servicio_monitoreo = MonitoringService(servicio_configuracion, servicio_interfaces,
                                           servicio_descubrimiento, servicio_lista_blanca,
                                           aislamiento=servicio_aislamiento, bitacora=servicio_bitacora,
                                           notificaciones=servicio_notificaciones)

    vista_resumen = ResumenView()
    vista_dispositivos = DeviceView()
    vista_lista_blanca = WhitelistView()
    vista_aislamiento = IsolationView()
    vista_bitacora = BitacoraView()
    vista_reporte = ReporteView()
    vista_configuracion = SettingsView()
    vista_ayuda = AyudaView(MANUALES)
    ventana = MainWindow({"Resumen": vista_resumen,
                          "Dispositivos": vista_dispositivos,
                          "Lista blanca": vista_lista_blanca,
                          "Aislamiento": vista_aislamiento,
                          "Bitácora": vista_bitacora,
                          "Reportes": vista_reporte,
                          "Configuración": vista_configuracion,
                          "Ayuda": vista_ayuda},
                         inicial="Resumen")

    # Aislar/desbloquear se ejecutan fuera del hilo de la interfaz (L4).
    ejecutor = EjecutorAislamiento(servicio_aislamiento, asincrono=True, parent=ventana)
    monitoreo = MonitoringController(servicio_monitoreo, servicio_configuracion, parent=ventana)
    dispositivos = DeviceController(vista_dispositivos, monitoreo, servicio_monitoreo,
                                    servicio_lista_blanca, servicio_aislamiento, parent=ventana,
                                    ejecutor=ejecutor, bitacora=servicio_bitacora)
    lista_blanca = WhitelistController(vista_lista_blanca, servicio_lista_blanca,
                                       servicio_monitoreo, servicio_aislamiento, parent=ventana,
                                       ejecutor=ejecutor)
    aislamiento = IsolationController(vista_aislamiento, servicio_aislamiento,
                                      servicio_lista_blanca, servicio_monitoreo,
                                      ejecutor=ejecutor, parent=ventana)
    bitacora = BitacoraController(vista_bitacora, servicio_bitacora, parent=ventana)
    reporte = ReporteController(vista_reporte, servicio_reportes, parent=ventana)
    configuracion = SettingsController(vista_configuracion, servicio_configuracion,
                                       servicio_interfaces, parent=ventana)
    notificaciones = NotificacionController(vista_configuracion, servicio_notificaciones,
                                            parent=ventana)
    resumen = ResumenController(vista_resumen, servicio_monitoreo, servicio_lista_blanca,
                                servicio_aislamiento, servicio_bitacora,
                                controlador_monitoreo=monitoreo, ejecutor=ejecutor, parent=ventana)
    monitoreo.indicadorCambiado.connect(ventana.set_indicador)
    configuracion.configuracionCambiada.connect(monitoreo.reevaluar)
    lista_blanca.irADispositivos.connect(lambda: ventana.ir_a("Dispositivos"))
    return Aplicacion(ventana, monitoreo, configuracion, dispositivos, lista_blanca,
                      servicio_aislamiento, servicio_lista_blanca, aislamiento, ejecutor,
                      bitacora, reporte, servicio_notificaciones, notificaciones, resumen)


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

    # Instancia única (H2): se comprueba ANTES de abrir cualquier archivo de datos.
    directorio = directorio_datos()
    # L5: nunca compartir carpeta con versiones anteriores (no respetan el bloqueo).
    problema = problema_carpeta_datos(directorio)
    if problema is not None:
        QMessageBox.critical(None, "CYBERA", f"{problema}\n\nNo se abrió CYBERA y no se "
                             "modificó ningún archivo.")
        return 1
    instancia = InstanciaUnica(directorio)
    resultado = instancia.adquirir()
    if resultado is ResultadoBloqueo.OTRA_INSTANCIA:
        QMessageBox.information(None, "CYBERA", f"{instancia.detalle}\n\nCierre la otra "
                                "ventana de CYBERA antes de abrir una nueva.")
        return 1
    if resultado is not ResultadoBloqueo.ADQUIRIDO:
        QMessageBox.critical(None, "CYBERA", f"{instancia.detalle}\n\nNo se abrió CYBERA para "
                             "no arriesgar la integridad de los archivos de datos.")
        return 1

    try:
        aplicacion = construir(directorio)
        pantalla = QGuiApplication.primaryScreen().availableGeometry()
        aplicacion.ventana.resize(min(1440, pantalla.width()), min(900, pantalla.height()))
        aplicacion.ventana.show()
        aplicacion.monitoreo.iniciar()

        def al_salir() -> None:
            # Retira las operaciones que aún esperan y aguarda a las que ya se
            # ejecutan: no se abandona una operación de red a medias.
            aplicacion.ejecutor.detener()
            aplicacion.monitoreo.detener()       # Cancela el ciclo y descarta el inventario.
            aplicacion.configuracion.detener()
            if aplicacion.servicio_notificaciones is not None:
                aplicacion.servicio_notificaciones.detener()  # Deja de reintentar correos.

        app.aboutToQuit.connect(al_salir)
        return app.exec()
    finally:
        instancia.liberar()                      # También si construir() falla.
