"""Ejecución de aislar/desbloquear fuera del hilo de la interfaz (limitación L4).

El futuro motor de red puede tardar (privilegios, tramas, verificación). Este
ejecutor lanza ``IsolationService.aislar``/``desbloquear`` en un ``QThreadPool``
mediante ``TareaFondo`` y devuelve el resultado al hilo de la interfaz con
señales Qt (conexión en cola). Los controladores nunca llaman al servicio
directamente.

- Duplicados: una MAC con una petición pendiente o en ejecución no admite otra
  (``solicitar`` devuelve False). Además, IsolationService aplica su propia
  exclusión por MAC, compartida con la lista blanca.
- Errores: llegan como la excepción original (``fallida``), para que la interfaz
  distinga «no disponible», «fallido» y «requiere recuperación».
- Cancelación SOLO si es segura: una petición que aún espera en la cola se puede
  retirar (``cancelar``); una que ya se está ejecutando NO, porque el motor pudo
  haber actuado en la red. Al cerrar se retiran las que esperan y se aguarda a
  las que están en ejecución (``detener``).
- ``asincrono=False`` ejecuta en el mismo hilo y emite las mismas señales; lo
  usan las pruebas y los controladores construidos sin ejecutor. La aplicación
  real (``app/main.py``) usa siempre el modo asíncrono.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThreadPool, Signal

from app.controllers.tareas import TareaFondo
from app.models.mac import normalizar_mac
from app.models.operacion_aislamiento import TipoOperacion

AISLAR = TipoOperacion.AISLAR.value
DESBLOQUEAR = TipoOperacion.DESBLOQUEAR.value


class EjecutorAislamiento(QObject):
    iniciada = Signal(str, str, object)                 # mac, tipo, contexto
    terminada = Signal(str, str, object, object)        # mac, tipo, contexto, resultado
    fallida = Signal(str, str, object, object)          # mac, tipo, contexto, excepción
    cancelada = Signal(str, str, object)                # mac, tipo, contexto

    def __init__(self, servicio, asincrono: bool = True, max_hilos: int = 4,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._servicio = servicio
        self._asincrono = asincrono
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_hilos)          # MAC distintas en paralelo.
        self._pendientes: dict[str, tuple[TareaFondo | None, str, object]] = {}
        self._cerrando = False

    @property
    def asincrono(self) -> bool:
        return self._asincrono

    def en_curso(self, mac: str) -> bool:
        return _clave(mac) in self._pendientes

    def solicitar(self, tipo: str, mac: str, actor: str, contexto: object = None) -> bool:
        """Encola la operación. False si ya hay una para esa MAC o si se está cerrando."""
        if tipo not in (AISLAR, DESBLOQUEAR):
            raise ValueError(f"Operación desconocida: {tipo}")
        clave = _clave(mac)
        if self._cerrando or clave in self._pendientes:
            return False
        funcion = self._servicio.aislar if tipo == AISLAR else self._servicio.desbloquear
        if not self._asincrono:
            self._pendientes[clave] = (None, tipo, contexto)
            self.iniciada.emit(clave, tipo, contexto)
            try:
                resultado = funcion(mac, actor)
            except Exception as error:  # noqa: BLE001
                self._pendientes.pop(clave, None)
                self.fallida.emit(clave, tipo, contexto, error)
            else:
                self._pendientes.pop(clave, None)
                self.terminada.emit(clave, tipo, contexto, resultado)
            return True

        tarea = TareaFondo(funcion, mac, actor, contexto=(clave, tipo, contexto))
        tarea.senales.terminado.connect(self._al_terminar)
        tarea.senales.error.connect(self._al_fallar)
        self._pendientes[clave] = (tarea, tipo, contexto)
        self.iniciada.emit(clave, tipo, contexto)
        self._pool.start(tarea)
        return True

    def cancelar(self, mac: str) -> bool:
        """Retira la petición si AÚN NO empezó. Nunca interrumpe una en ejecución."""
        clave = _clave(mac)
        tarea, tipo, contexto = self._pendientes.get(clave, (None, None, None))
        if tarea is None or not self._pool.tryTake(tarea):
            return False
        self._pendientes.pop(clave, None)
        self.cancelada.emit(clave, tipo, contexto)
        return True

    def detener(self, espera_ms: int = 30000) -> bool:
        """Cierre ordenado: no acepta nuevas, retira las que esperan y aguarda a
        las que ya se ejecutan (no se abandona una operación de red a medias)."""
        self._cerrando = True
        for clave in list(self._pendientes):
            self.cancelar(clave)
        return self._pool.waitForDone(espera_ms)

    # --- Resultados (hilo de la interfaz) ------------------------------------------

    def _al_terminar(self, contexto, resultado) -> None:
        clave, tipo, origen = contexto
        self._pendientes.pop(clave, None)
        self.terminada.emit(clave, tipo, origen, resultado)

    def _al_fallar(self, contexto, error) -> None:
        clave, tipo, origen = contexto
        self._pendientes.pop(clave, None)
        self.fallida.emit(clave, tipo, origen, error)


def _clave(mac: str) -> str:
    try:
        return normalizar_mac(mac)
    except ValueError:
        return str(mac)
