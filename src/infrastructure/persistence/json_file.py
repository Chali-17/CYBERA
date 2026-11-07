"""Acceso seguro a un archivo JSON local (Arquitectura, 12.1)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class ArchivoDatosError(Exception):
    """El archivo existe pero no se puede leer o escribir de forma segura."""


_candados: dict[str, threading.RLock] = {}
_candado_registro = threading.Lock()


def _candado_de(ruta: Path) -> threading.RLock:
    clave = os.path.normcase(os.path.abspath(ruta))
    with _candado_registro:
        return _candados.setdefault(clave, threading.RLock())


class JsonFile:
    """Lectura y escritura atómica de un archivo JSON.

    - Las escrituras se serializan con un candado (escrituras concurrentes).
    - Se escribe en un temporal y se reemplaza el original con ``os.replace``;
      así un corte a mitad de escritura no deja el archivo a medias.
    - Si el archivo está dañado, se informa el error y NUNCA se sobrescribe.
    """

    def __init__(self, ruta: Path) -> None:
        self.ruta = Path(ruta)
        # Un candado por archivo en todo el proceso: dos JsonFile sobre la misma
        # ruta (p. ej. dos repositorios) comparten candado y no pierden escrituras.
        self.lock = _candado_de(self.ruta)

    def leer(self) -> Any | None:
        with self.lock:
            if not self.ruta.exists():
                return None
            try:
                with self.ruta.open("r", encoding="utf-8") as archivo:
                    return json.load(archivo)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ArchivoDatosError(
                    f"El archivo «{self.ruta}» está dañado y no se modificó ({error})."
                ) from error
            except OSError as error:
                raise ArchivoDatosError(f"No se pudo leer «{self.ruta}»: {error}") from error

    def escribir(self, datos: Any) -> None:
        with self.lock:
            temporal = self.ruta.with_name(self.ruta.name + ".tmp")
            try:
                self.ruta.parent.mkdir(parents=True, exist_ok=True)
                with temporal.open("w", encoding="utf-8") as archivo:
                    json.dump(datos, archivo, ensure_ascii=False, indent=2)
                    archivo.flush()
                    os.fsync(archivo.fileno())
                os.replace(temporal, self.ruta)
            except OSError as error:
                try:
                    temporal.unlink(missing_ok=True)
                except OSError:
                    pass
                raise ArchivoDatosError(f"No se pudo guardar «{self.ruta}»: {error}") from error
