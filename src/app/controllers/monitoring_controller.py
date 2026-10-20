"""MonitoringController: inicia, detiene y temporiza el ciclo de monitoreo."""

from __future__ import annotations

import threading
import time
from enum import Enum

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from app.controllers.tareas import TareaFondo
from app.services.monitoring_service import (INTERVALO_ESCANEO_S, MonitoringService,
                                             ResultadoCiclo, TipoResultado)
from app.services.settings_service import SettingsService


class EstadoIndicador(Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"
    ERROR = "ERROR"


class MonitoringController(QObject):
    indicadorCambiado = Signal(object)    # EstadoIndicador
    resultadoCiclo = Signal(object)       # ResultadoCiclo
    escaneoIniciado = Signal(str)         # nombre de la interfaz

    def __init__(self, servicio: MonitoringService, configuracion: SettingsService,
                 intervalo_s: float = INTERVALO_ESCANEO_S, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._servicio = servicio
        self._configuracion = configuracion
        self._intervalo = intervalo_s
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)          # Un solo ciclo a la vez.
        self._temporizador = QTimer(self)
        self._temporizador.setInterval(1000)
        self._temporizador.timeout.connect(self._revisar_temporizador)
        self._activo = False
        self._interfaz_id: str | None = None
        self._nombre_interfaz = ""
        self._generacion = 0
        self._cancelar = threading.Event()
        self._en_curso: TareaFondo | None = None
        self._fin_ultimo_ciclo: float | None = None
        self._relanzar = False

    # --- API pública -------------------------------------------------------
    @property
    def activo(self) -> bool:
        return self._activo

    def iniciar(self) -> None:
        self.reevaluar()
        self._temporizador.start()

    def reevaluar(self) -> None:
        """Lee la configuración y aplica el estado (llamar tras cada cambio)."""
        try:
            cfg = self._configuracion.cargar()
        except Exception as error:  # noqa: BLE001
            self._invalidar()
            self._activo = False
            self._servicio.detener()
            self.indicadorCambiado.emit(EstadoIndicador.ERROR)
            self.resultadoCiclo.emit(ResultadoCiclo(
                TipoResultado.ERROR, mensaje=f"No se pudo leer la configuración: {error}"))
            return
        cambio = (cfg.monitoreo_activo != self._activo) or (cfg.interfaz_id != self._interfaz_id)
        self._activo = cfg.monitoreo_activo
        self._interfaz_id = cfg.interfaz_id
        self._nombre_interfaz = cfg.nombre_interfaz or ""
        if cambio:
            self._invalidar()
        if not self._activo:
            self._servicio.detener()
            self.indicadorCambiado.emit(EstadoIndicador.INACTIVO)
            self.resultadoCiclo.emit(ResultadoCiclo(
                TipoResultado.MONITOREO_INACTIVO,
                mensaje="El monitoreo está inactivo. Actívelo en Configuración."))
            return
        self.indicadorCambiado.emit(EstadoIndicador.ACTIVO)
        if cambio:
            self._servicio.detener()
            self._fin_ultimo_ciclo = None
            self._lanzar()

    def detener(self) -> None:
        """Cierre de la aplicación: cancela el ciclo y descarta el inventario."""
        self._temporizador.stop()
        self._invalidar()
        self._pool.clear()
        self._pool.waitForDone(10000)
        self._servicio.detener()

    # --- Interno -----------------------------------------------------------
    def _invalidar(self) -> None:
        """Hace que cualquier ciclo en curso se cancele y su resultado se descarte."""
        self._generacion += 1
        self._cancelar.set()
        self._cancelar = threading.Event()
        if self._en_curso is not None:
            self._relanzar = True

    def _revisar_temporizador(self) -> None:
        if not self._activo or self._en_curso is not None:
            return
        if self._fin_ultimo_ciclo is None or time.monotonic() - self._fin_ultimo_ciclo >= self._intervalo:
            self._lanzar()

    def _lanzar(self) -> None:
        if not self._activo:
            return
        if self._en_curso is not None:
            self._relanzar = True
            return
        self._relanzar = False
        tarea = TareaFondo(self._servicio.ejecutar_ciclo, self._cancelar, contexto=self._generacion)
        tarea.senales.terminado.connect(self._al_terminar)
        tarea.senales.fallido.connect(self._al_fallar)
        self._en_curso = tarea
        self.escaneoIniciado.emit(self._nombre_interfaz)
        self._pool.start(tarea)

    def _cerrar_ciclo(self) -> None:
        """Marca el fin del ciclo y relanza si la configuración cambió mientras corría."""
        self._en_curso = None
        self._fin_ultimo_ciclo = time.monotonic()
        if self._relanzar and self._activo:
            self._fin_ultimo_ciclo = None
            QTimer.singleShot(0, self._lanzar)

    def _al_terminar(self, generacion: int, resultado: ResultadoCiclo) -> None:
        self._cerrar_ciclo()
        if generacion != self._generacion or not self._activo:
            return  # Resultado obsoleto: el monitoreo cambió durante el ciclo.
        if resultado.tipo is TipoResultado.CANCELADO:
            return
        if resultado.tipo is TipoResultado.ACTUALIZADO:
            self.indicadorCambiado.emit(EstadoIndicador.ACTIVO)
        elif resultado.tipo is TipoResultado.MONITOREO_INACTIVO:
            self.indicadorCambiado.emit(EstadoIndicador.INACTIVO)
        else:
            self.indicadorCambiado.emit(EstadoIndicador.ERROR)
        self.resultadoCiclo.emit(resultado)

    def _al_fallar(self, generacion: int, mensaje: str) -> None:
        self._cerrar_ciclo()
        if generacion != self._generacion or not self._activo:
            return
        self._servicio.detener()
        self.indicadorCambiado.emit(EstadoIndicador.ERROR)
        self.resultadoCiclo.emit(ResultadoCiclo(TipoResultado.ERROR,
                                                mensaje=f"El ciclo de monitoreo falló: {mensaje}"))
