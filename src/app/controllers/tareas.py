"""Ejecución en segundo plano compatible con PySide6.

La función corre en un hilo del QThreadPool; el resultado vuelve al hilo de la
interfaz mediante una señal (conexión en cola), de modo que la GUI nunca se
bloquea durante operaciones de red.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

_log = logging.getLogger(__name__)


class _Senales(QObject):
    terminado = Signal(object, object)   # (contexto, resultado)
    fallido = Signal(object, str)        # (contexto, mensaje)
    error = Signal(object, object)       # (contexto, excepción) — para distinguir su tipo


class TareaFondo(QRunnable):
    def __init__(self, funcion: Callable[..., Any], *argumentos: Any, contexto: Any = None) -> None:
        super().__init__()
        # Quien lanza la tarea conserva la referencia hasta recibir su resultado.
        self.setAutoDelete(False)
        self._funcion = funcion
        self._argumentos = argumentos
        self._contexto = contexto
        # Se crea en el hilo de la GUI: sus señales se entregan en ese hilo.
        self.senales = _Senales()

    def run(self) -> None:  # Hilo de trabajo
        try:
            resultado = self._funcion(*self._argumentos)
        except Exception as error:  # noqa: BLE001
            _log.exception("Tarea en segundo plano fallida")
            self.senales.error.emit(self._contexto, error)
            self.senales.fallido.emit(self._contexto, str(error) or type(error).__name__)
        else:
            self.senales.terminado.emit(self._contexto, resultado)
