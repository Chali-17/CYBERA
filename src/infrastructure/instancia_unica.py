"""Instancia única de CYBERA por carpeta de datos (corrección H2).

Usa ``QLockFile`` sobre ``<directorio de datos>\\cybera.lock`` (por defecto
``%APPDATA%\\CYBERA\\cybera.lock``). Mientras una instancia lo mantiene, otra que
apunte a la misma carpeta no arranca y, por tanto, no toca lista_blanca.json,
aislamientos.json ni configuracion.json.

- ``setStaleLockTime(0)``: un bloqueo nunca caduca por antigüedad (CYBERA puede
  ejecutarse durante días). Si el proceso que lo creó murió, Qt lo detecta por
  su PID y permite recuperarlo.
- Es la única exclusión entre procesos del sistema; las reservas por MAC y los
  candados de JsonFile solo coordinan hilos de un mismo proceso.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import QLockFile

NOMBRE_BLOQUEO = "cybera.lock"


class ResultadoBloqueo(Enum):
    ADQUIRIDO = "ADQUIRIDO"
    OTRA_INSTANCIA = "OTRA_INSTANCIA"   # Otra instancia viva mantiene el bloqueo.
    ERROR = "ERROR"                     # Sin permisos u otro fallo: no es seguro continuar.


class InstanciaUnica:
    def __init__(self, directorio: Path, espera_ms: int = 200) -> None:
        self.ruta = Path(directorio) / NOMBRE_BLOQUEO
        self._espera_ms = espera_ms
        self._bloqueo: QLockFile | None = None
        self.detalle: str | None = None

    @property
    def adquirido(self) -> bool:
        return self._bloqueo is not None and self._bloqueo.isLocked()

    def adquirir(self) -> ResultadoBloqueo:
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.detalle = f"No se pudo crear la carpeta de datos «{self.ruta.parent}»: {error}"
            return ResultadoBloqueo.ERROR
        bloqueo = QLockFile(str(self.ruta))
        bloqueo.setStaleLockTime(0)
        if bloqueo.tryLock(self._espera_ms):
            self._bloqueo = bloqueo
            self.detalle = None
            return ResultadoBloqueo.ADQUIRIDO
        if bloqueo.error() == QLockFile.LockError.LockFailedError:
            self.detalle = "CYBERA ya se está ejecutando con esta carpeta de datos."
            return ResultadoBloqueo.OTRA_INSTANCIA
        self.detalle = (f"No se pudo crear el bloqueo de instancia «{self.ruta}» "
                        f"({bloqueo.error().name}).")
        return ResultadoBloqueo.ERROR

    def liberar(self) -> None:
        if self._bloqueo is not None:
            self._bloqueo.unlock()
            self._bloqueo = None
