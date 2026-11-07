"""notificaciones.json: SOLO el correo remitente (dato no secreto).

La contraseña de aplicación no se guarda aquí: vive en el Administrador de
credenciales de Windows (ver ``infrastructure/secretos.py``).

Estructura: ``{"version": 1, "remitente": "usuario@gmail.com" | null}``.
"""

from __future__ import annotations

from pathlib import Path

from infrastructure.persistence.json_file import ArchivoDatosError, JsonFile

VERSION_FORMATO = 1


class JsonNotificacionesRepository:
    def __init__(self, ruta: Path) -> None:
        self._archivo = JsonFile(ruta)

    @property
    def ruta(self) -> Path:
        return self._archivo.ruta

    def remitente(self) -> str | None:
        datos = self._archivo.leer()
        if datos is None:
            return None
        if not isinstance(datos, dict) or datos.get("version", 1) != VERSION_FORMATO:
            raise ArchivoDatosError(f"El archivo «{self.ruta}» no tiene la estructura esperada.")
        valor = datos.get("remitente")
        return valor if isinstance(valor, str) and valor else None

    def guardar_remitente(self, remitente: str | None) -> None:
        self._archivo.escribir({"version": VERSION_FORMATO, "remitente": remitente})
