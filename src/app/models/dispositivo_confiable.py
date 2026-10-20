"""DispositivoConfiable (Modelo de datos, 6.2) persistido en lista_blanca.json."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.models.mac import normalizar_mac

LONGITUD_MAXIMA_ALIAS = 64


class OrigenRegistro(Enum):
    ESCANEO = "ESCANEO"
    MANUAL = "MANUAL"
    IMPORTACION = "IMPORTACION"


def limpiar_alias(alias: str | None) -> str | None:
    """Alias opcional: sin espacios sobrantes; vacío equivale a sin alias."""
    if alias is None:
        return None
    texto = " ".join(str(alias).split())
    if not texto:
        return None
    if len(texto) > LONGITUD_MAXIMA_ALIAS:
        raise ValueError(f"El alias no puede superar {LONGITUD_MAXIMA_ALIAS} caracteres.")
    return texto


@dataclass(frozen=True)
class DispositivoConfiable:
    mac: str
    alias: str | None
    fecha_autorizacion: datetime
    origen_registro: OrigenRegistro
    activo: bool = True

    def a_dict(self) -> dict:
        return {
            "mac": self.mac,
            "alias": self.alias,
            "fechaAutorizacion": self.fecha_autorizacion.isoformat(timespec="seconds"),
            "origenRegistro": self.origen_registro.value,
            "activo": self.activo,
        }

    @classmethod
    def desde_dict(cls, datos: dict) -> "DispositivoConfiable":
        return cls(
            mac=normalizar_mac(datos["mac"]),
            alias=limpiar_alias(datos.get("alias")),
            fecha_autorizacion=datetime.fromisoformat(datos["fechaAutorizacion"]),
            origen_registro=OrigenRegistro(datos["origenRegistro"]),
            activo=bool(datos.get("activo", True)),
        )
