"""SettingsService: interfaz seleccionada y estado del monitoreo (RF12, CU-01)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.models.configuracion import ConfiguracionSistema, EstadoMonitoreo
from app.models.interfaz_red import InterfazRed
from infrastructure.interfaces import ISettingsRepository


class ConfiguracionInvalidaError(ValueError):
    pass


class SettingsService:
    def __init__(self, repositorio: ISettingsRepository,
                 reloj: Callable[[], datetime] = datetime.now) -> None:
        self._repo = repositorio
        self._reloj = reloj

    def cargar(self) -> ConfiguracionSistema:
        return self._repo.load()

    def _guardar(self, configuracion: ConfiguracionSistema) -> ConfiguracionSistema:
        configuracion = configuracion.con(fecha_configuracion=self._reloj().replace(microsecond=0))
        self._repo.save(configuracion)
        return configuracion

    def seleccionar_interfaz(self, interfaz: InterfazRed) -> ConfiguracionSistema:
        actual = self._repo.load()
        return self._guardar(actual.con(interfaz_id=interfaz.id,
                                        nombre_interfaz=interfaz.nombre,
                                        tipo_interfaz=interfaz.tipo))

    def activar_monitoreo(self) -> ConfiguracionSistema:
        actual = self._repo.load()
        if not actual.interfaz_id:
            raise ConfiguracionInvalidaError(
                "Seleccione una interfaz de red antes de activar el monitoreo.")
        return self._guardar(actual.con(estado_monitoreo=EstadoMonitoreo.ACTIVO))

    def desactivar_monitoreo(self) -> ConfiguracionSistema:
        actual = self._repo.load()
        return self._guardar(actual.con(estado_monitoreo=EstadoMonitoreo.INACTIVO))
