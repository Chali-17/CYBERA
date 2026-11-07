"""Repositorio de la lista blanca en lista_blanca.json (Modelo de datos, 4.1)."""

from __future__ import annotations

from pathlib import Path

from app.models.dispositivo_confiable import DispositivoConfiable
from app.models.mac import normalizar_mac
from infrastructure.interfaces import IWhitelistRepository
from infrastructure.persistence.json_file import ArchivoDatosError, JsonFile

VERSION_FORMATO = 1


class JsonWhitelistRepository(IWhitelistRepository):
    """Estructura: ``{"version": 1, "dispositivos": [DispositivoConfiable, ...]}``."""

    def __init__(self, ruta: Path) -> None:
        self._archivo = JsonFile(ruta)

    @property
    def ruta(self) -> Path:
        return self._archivo.ruta

    def _leer_todos(self) -> list[DispositivoConfiable]:
        datos = self._archivo.leer()
        if datos is None:
            return []
        if not isinstance(datos, dict) or not isinstance(datos.get("dispositivos"), list):
            raise ArchivoDatosError(
                f"El archivo «{self.ruta}» no tiene la estructura esperada y no se modificó.")
        try:
            return [DispositivoConfiable.desde_dict(d) for d in datos["dispositivos"]]
        except (KeyError, TypeError, ValueError) as error:
            raise ArchivoDatosError(
                f"El archivo «{self.ruta}» contiene un registro inválido ({error}) "
                f"y no se modificó.") from error

    def _guardar_todos(self, dispositivos: list[DispositivoConfiable]) -> None:
        self._archivo.escribir({
            "version": VERSION_FORMATO,
            "dispositivos": [d.a_dict() for d in dispositivos],
        })

    def list(self) -> list[DispositivoConfiable]:
        with self._archivo.lock:
            return self._leer_todos()

    def exists(self, mac: str) -> bool:
        mac = normalizar_mac(mac)
        return any(d.mac == mac and d.activo for d in self.list())

    def add(self, dispositivo: DispositivoConfiable) -> None:
        """Agrega una autorización. Un registro inactivo de la misma MAC se reemplaza."""
        with self._archivo.lock:
            actuales = self._leer_todos()
            if any(d.mac == dispositivo.mac and d.activo for d in actuales):
                raise ValueError(f"La MAC {dispositivo.mac} ya está autorizada (RI-02).")
            restantes = [d for d in actuales if d.mac != dispositivo.mac]
            self._guardar_todos(restantes + [dispositivo])

    def remove(self, mac: str) -> None:
        mac = normalizar_mac(mac)
        with self._archivo.lock:
            actuales = self._leer_todos()
            self._guardar_todos([d for d in actuales if d.mac != mac])

    def actualizar_alias(self, mac: str, alias: str | None) -> DispositivoConfiable:
        """Reemplaza el alias conservando MAC, fecha, origen y estado (no duplica)."""
        import dataclasses
        mac = normalizar_mac(mac)
        with self._archivo.lock:
            actuales = self._leer_todos()
            nuevos, actualizado = [], None
            for d in actuales:
                if d.mac == mac and d.activo:
                    actualizado = dataclasses.replace(d, alias=alias)
                    nuevos.append(actualizado)
                else:
                    nuevos.append(d)
            if actualizado is None:
                raise ValueError(f"La MAC {mac} no está en la lista blanca.")
            self._guardar_todos(nuevos)
            return actualizado
