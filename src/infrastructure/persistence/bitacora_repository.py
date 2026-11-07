"""Repositorio de la bitácora en bitacora.json (módulo Bitácora).

Guarda el historial de eventos mediante el mismo mecanismo de almacenamiento
local que el resto de datos (``JsonFile``: escritura atómica temporal + ``os.replace``).

Estructura: ``{"version": 1, "eventos": [EventoBitacora, ...]}``.

- Si el archivo no existe, el historial está vacío.
- Un archivo dañado o con formato desconocido se informa mediante
  ``ArchivoDatosError`` y NUNCA se sobrescribe.
- ``vaciar`` es la operación de depuración manual (CU-10): vacía el historial.
"""

from __future__ import annotations

from pathlib import Path

from app.models.evento_bitacora import EventoBitacora
from infrastructure.interfaces import IBitacoraRepository
from infrastructure.persistence.json_file import ArchivoDatosError, JsonFile

VERSION_FORMATO = 1


class JsonBitacoraRepository(IBitacoraRepository):
    def __init__(self, ruta: Path) -> None:
        self._archivo = JsonFile(ruta)

    @property
    def ruta(self) -> Path:
        return self._archivo.ruta

    # --- Lectura / escritura ------------------------------------------------------

    def _leer(self) -> list[EventoBitacora]:
        datos = self._archivo.leer()
        if datos is None:
            return []
        if not isinstance(datos, dict) or not isinstance(datos.get("eventos"), list):
            raise ArchivoDatosError(
                f"El archivo «{self.ruta}» no tiene la estructura esperada y no se modificó.")
        version = datos.get("version", 1)
        # type() y no isinstance(): bool es subclase de int y True == 1 (H5).
        if type(version) is not int or version != VERSION_FORMATO:
            raise ArchivoDatosError(
                f"El archivo «{self.ruta}» usa un formato desconocido (versión {version!r}) y no se modificó.")
        try:
            return [EventoBitacora.desde_dict(d) for d in datos["eventos"]]
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ArchivoDatosError(
                f"El archivo «{self.ruta}» contiene un registro inválido ({error}) y no se modificó."
            ) from error

    def agregar(self, evento: EventoBitacora) -> EventoBitacora:
        """Añade un evento al final del historial y lo persiste (escritura atómica)."""
        with self._archivo.lock:
            eventos = self._leer()
            if any(e.id == evento.id for e in eventos):
                raise ValueError(f"Ya existe el evento {evento.id}.")
            eventos.append(evento)
            self._archivo.escribir({"version": VERSION_FORMATO, "eventos": [e.a_dict() for e in eventos]})
            return evento

    def eventos(self) -> list[EventoBitacora]:
        with self._archivo.lock:
            return self._leer()

    def vaciar(self) -> None:
        """Elimina todos los eventos (depuración manual, CU-10)."""
        with self._archivo.lock:
            self._archivo.escribir({"version": VERSION_FORMATO, "eventos": []})
