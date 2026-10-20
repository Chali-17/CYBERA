"""Repositorio de configuracion.json (Modelo de datos, 4.1 y 6.6)."""

from __future__ import annotations

from pathlib import Path

from app.models.configuracion import ConfiguracionSistema
from infrastructure.interfaces import ISettingsRepository
from infrastructure.persistence.json_file import ArchivoDatosError, JsonFile


class JsonSettingsRepository(ISettingsRepository):
    def __init__(self, ruta: Path) -> None:
        self._archivo = JsonFile(ruta)

    @property
    def ruta(self) -> Path:
        return self._archivo.ruta

    def load(self) -> ConfiguracionSistema:
        datos = self._archivo.leer()
        if datos is None:
            # Primera ejecución: sin interfaz y con el monitoreo inactivo.
            return ConfiguracionSistema()
        try:
            return ConfiguracionSistema.desde_dict(datos)
        except (TypeError, ValueError) as error:
            raise ArchivoDatosError(
                f"El archivo «{self.ruta}» tiene valores inválidos ({error}) y no se modificó."
            ) from error

    def save(self, configuracion: ConfiguracionSistema) -> None:
        self._archivo.escribir(configuracion.a_dict())
