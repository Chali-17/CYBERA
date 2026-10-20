"""ConfiguracionSistema (Modelo de datos, 6.6) persistida en configuracion.json."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from app.models.interfaz_red import TipoInterfaz


class EstadoMonitoreo(Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


@dataclass(frozen=True)
class ConfiguracionSistema:
    interfaz_id: str | None = None
    nombre_interfaz: str | None = None
    tipo_interfaz: TipoInterfaz | None = None
    estado_monitoreo: EstadoMonitoreo = EstadoMonitoreo.INACTIVO
    fecha_configuracion: datetime | None = None

    @property
    def monitoreo_activo(self) -> bool:
        return self.estado_monitoreo is EstadoMonitoreo.ACTIVO

    def con(self, **cambios) -> "ConfiguracionSistema":
        return replace(self, **cambios)

    def a_dict(self) -> dict:
        return {
            "interfazId": self.interfaz_id,
            "nombreInterfaz": self.nombre_interfaz,
            "tipoInterfaz": self.tipo_interfaz.value if self.tipo_interfaz else None,
            "estadoMonitoreo": self.estado_monitoreo.value,
            "fechaConfiguracion": (self.fecha_configuracion.isoformat(timespec="seconds")
                                   if self.fecha_configuracion else None),
        }

    @classmethod
    def desde_dict(cls, datos: dict) -> "ConfiguracionSistema":
        if not isinstance(datos, dict):
            raise ValueError("La configuración debe ser un objeto JSON.")
        tipo = datos.get("tipoInterfaz")
        fecha = datos.get("fechaConfiguracion")
        return cls(
            interfaz_id=datos.get("interfazId") or None,
            nombre_interfaz=datos.get("nombreInterfaz") or None,
            tipo_interfaz=TipoInterfaz(tipo) if tipo else None,
            estado_monitoreo=EstadoMonitoreo(datos.get("estadoMonitoreo", "INACTIVO")),
            fecha_configuracion=datetime.fromisoformat(fecha) if fecha else None,
        )
