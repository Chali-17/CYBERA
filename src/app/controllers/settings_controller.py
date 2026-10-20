"""SettingsController: selección de interfaz y activación del monitoreo (RF12)."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThreadPool, Signal

from app.controllers.tareas import TareaFondo
from app.models.interfaz_red import InterfazRed
from app.services.network_interface_service import NetworkInterfaceService
from app.services.settings_service import ConfiguracionInvalidaError, SettingsService


class SettingsController(QObject):
    configuracionCambiada = Signal()

    def __init__(self, vista, configuracion: SettingsService,
                 interfaces: NetworkInterfaceService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vista = vista
        self._configuracion = configuracion
        self._servicio_interfaces = interfaces
        self._interfaces: dict[str, InterfazRed] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._tarea: TareaFondo | None = None
        vista.mostrada.connect(self.cargar_interfaces)
        vista.interfazElegida.connect(self._elegir_interfaz)
        vista.alternarMonitoreo.connect(self._alternar_monitoreo)

    def cargar_interfaces(self) -> None:
        if self._tarea is not None:
            return
        self._vista.mostrar_cargando_interfaces()
        self._mostrar_estado()
        tarea = TareaFondo(self._servicio_interfaces.listar)
        tarea.senales.terminado.connect(self._interfaces_listas)
        tarea.senales.fallido.connect(self._interfaces_fallidas)
        self._tarea = tarea
        self._pool.start(tarea)

    def detener(self) -> None:
        self._pool.waitForDone(10000)

    def _interfaces_listas(self, _contexto, interfaces: list[InterfazRed]) -> None:
        self._tarea = None
        self._interfaces = {i.id: i for i in interfaces}
        cfg = self._cargar_configuracion()
        if cfg is None:
            return
        self._vista.mostrar_interfaces(interfaces, cfg.interfaz_id, cfg.nombre_interfaz)
        if cfg.interfaz_id and cfg.interfaz_id not in self._interfaces:
            self._vista.mostrar_aviso(
                f"La interfaz guardada «{cfg.nombre_interfaz}» no está presente en el equipo.",
                exito=False)
        self._mostrar_estado()

    def _interfaces_fallidas(self, _contexto, mensaje: str) -> None:
        self._tarea = None
        self._vista.mostrar_error_interfaces(f"No se pudieron obtener las interfaces de red: {mensaje}")

    def _cargar_configuracion(self):
        try:
            return self._configuracion.cargar()
        except Exception as error:  # noqa: BLE001
            self._vista.mostrar_aviso(f"No se pudo leer la configuración: {error}", exito=False)
            return None

    def _mostrar_estado(self) -> None:
        cfg = self._cargar_configuracion()
        if cfg is not None:
            self._vista.mostrar_estado_monitoreo(cfg.monitoreo_activo, bool(cfg.interfaz_id))

    def _elegir_interfaz(self, interfaz_id: str) -> None:
        interfaz = self._interfaces.get(interfaz_id)
        if interfaz is None:
            return
        cfg = self._cargar_configuracion()
        if cfg is None or cfg.interfaz_id == interfaz.id:
            return
        try:
            self._configuracion.seleccionar_interfaz(interfaz)
        except Exception as error:  # noqa: BLE001
            self._vista.mostrar_aviso(f"No se pudo guardar la interfaz: {error}", exito=False)
            return
        motivo = interfaz.motivo_no_utilizable()
        if motivo:
            self._vista.mostrar_aviso(f"Interfaz «{interfaz.nombre}» guardada. Atención: {motivo}",
                                      exito=False)
        else:
            self._vista.mostrar_aviso(f"Interfaz «{interfaz.nombre}» guardada.", exito=True)
        self._mostrar_estado()
        self.configuracionCambiada.emit()

    def _alternar_monitoreo(self) -> None:
        cfg = self._cargar_configuracion()
        if cfg is None:
            return
        try:
            if cfg.monitoreo_activo:
                self._configuracion.desactivar_monitoreo()
                self._vista.mostrar_aviso("Monitoreo desactivado. No se realizarán nuevos escaneos.",
                                          exito=True)
            else:
                interfaz = self._interfaces.get(cfg.interfaz_id or "")
                if cfg.interfaz_id and self._interfaces and interfaz is None:
                    raise ConfiguracionInvalidaError(
                        f"La interfaz «{cfg.nombre_interfaz}» no está presente en el equipo. "
                        "Seleccione otra interfaz.")
                if interfaz is not None and interfaz.motivo_no_utilizable():
                    raise ConfiguracionInvalidaError(interfaz.motivo_no_utilizable())
                self._configuracion.activar_monitoreo()
                self._vista.mostrar_aviso(
                    f"Monitoreo activado en «{cfg.nombre_interfaz}».", exito=True)
        except ConfiguracionInvalidaError as error:
            self._vista.mostrar_aviso(str(error), exito=False)
            return
        except Exception as error:  # noqa: BLE001
            self._vista.mostrar_aviso(f"No se pudo guardar la configuración: {error}", exito=False)
            return
        self._mostrar_estado()
        self.configuracionCambiada.emit()
