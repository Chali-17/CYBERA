"""NotificacionController: configuración de notificaciones por correo (Configuración).

Coordina el panel «Notificaciones por correo electrónico» de la vista de
Configuración con el NotificacionService:
- Guardar la configuración (correo remitente + contraseña de aplicación).
- Enviar un correo de prueba y reportar el resultado REAL.
- Mostrar el estado: Configurado, No configurado o Error de conexión.

Guardado y prueba se ejecutan en segundo plano (QThreadPool) para no bloquear la
interfaz. La contraseña nunca se pide al servicio de vuelta ni se muestra.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThreadPool

from app.controllers.tareas import TareaFondo
from app.services.notificacion_service import (ConfiguracionCorreoError, EstadoConfiguracion,
                                               NotificacionService)
from infrastructure.correo.smtp_gmail import CorreoError


class NotificacionController(QObject):
    def __init__(self, vista, servicio: NotificacionService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vista = vista
        self._servicio = servicio
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._ocupado = False
        vista.guardarCorreoSolicitado.connect(self._guardar)
        vista.probarCorreoSolicitado.connect(self._probar)
        vista.mostrada.connect(self._mostrar_estado)
        self._mostrar_estado()

    # --- Estado -------------------------------------------------------------------
    def _mostrar_estado(self) -> None:
        try:
            estado = self._servicio.estado()
        except Exception as error:  # noqa: BLE001
            self._vista.mostrar_estado_correo("error", f"No se pudo leer la configuración: {error}")
            return
        self._vista.rellenar_correo(estado.remitente, estado.tiene_contrasena)
        if estado.configurado:
            self._vista.mostrar_estado_correo("configurado",
                                              "Notificaciones configuradas. Contraseña guardada.")
        else:
            self._vista.mostrar_estado_correo("no_configurado", "Notificaciones no configuradas.")

    # --- Guardar ------------------------------------------------------------------
    def _guardar(self, remitente: str, contrasena: str) -> None:
        if self._ocupado:
            return
        # Validación previa en el hilo de la interfaz (rápida, sin red).
        try:
            # El servicio valida de verdad; aquí solo evitamos lanzar la tarea en vano.
            if not (remitente or "").strip():
                raise ConfiguracionCorreoError("Indique el correo electrónico remitente.")
        except ConfiguracionCorreoError as error:
            self._vista.mostrar_estado_correo("error", str(error))
            return
        self._ocupado = True
        self._vista.set_correo_cargando(True, "Guardando configuración…")
        tarea = TareaFondo(self._servicio.guardar_config, remitente, contrasena)
        tarea.senales.terminado.connect(self._guardado_ok)
        tarea.senales.error.connect(self._guardado_error)
        self._tarea = tarea
        self._pool.start(tarea)

    def _guardado_ok(self, _ctx, estado: EstadoConfiguracion) -> None:
        self._ocupado = False
        self._vista.set_correo_cargando(False)
        self._vista.limpiar_contrasena()
        self._vista.rellenar_correo(estado.remitente, estado.tiene_contrasena)
        self._vista.mostrar_estado_correo(
            "configurado" if estado.configurado else "no_configurado",
            "Configuración guardada. Contraseña guardada de forma segura."
            if estado.configurado else "Configuración guardada, falta la contraseña de aplicación.")

    def _guardado_error(self, _ctx, error: Exception) -> None:
        self._ocupado = False
        self._vista.set_correo_cargando(False)
        mensaje = (str(error) if isinstance(error, ConfiguracionCorreoError)
                   else f"No se pudo guardar la configuración: {error}")
        self._vista.mostrar_estado_correo("error", mensaje)

    # --- Correo de prueba ---------------------------------------------------------
    def _probar(self, remitente: str, contrasena: str) -> None:
        if self._ocupado:
            return
        self._ocupado = True
        self._vista.set_correo_cargando(True, "Enviando correo de prueba…")

        def guardar_y_probar():
            # Si el usuario cambió el correo o escribió la contraseña, se guarda antes
            # de probar; si dejó la contraseña vacía, se usa la ya almacenada.
            self._servicio.guardar_config(remitente, contrasena)
            self._servicio.enviar_prueba()

        tarea = TareaFondo(guardar_y_probar)
        tarea.senales.terminado.connect(self._prueba_ok)
        tarea.senales.error.connect(self._prueba_error)
        self._tarea = tarea
        self._pool.start(tarea)

    def _prueba_ok(self, _ctx, _resultado) -> None:
        self._ocupado = False
        self._vista.set_correo_cargando(False)
        self._vista.limpiar_contrasena()
        estado = self._servicio.estado()
        self._vista.rellenar_correo(estado.remitente, estado.tiene_contrasena)
        self._vista.mostrar_estado_correo(
            "configurado", f"Correo de prueba enviado a {estado.remitente}. Revise su bandeja.")

    def _prueba_error(self, _ctx, error: Exception) -> None:
        self._ocupado = False
        self._vista.set_correo_cargando(False)
        if isinstance(error, (CorreoError, ConfiguracionCorreoError)):
            self._vista.mostrar_estado_correo("error", str(error))
        else:
            self._vista.mostrar_estado_correo("error", f"No se pudo enviar el correo de prueba: {error}")
