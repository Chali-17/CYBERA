"""AccionAislamiento (Modelo de datos, 6.4) persistida en aislamientos.json.

Representa una contención aplicada sobre una MAC. Solo debe crearse después de
que el motor de red CONFIRME el aislamiento; nunca como simple etiqueta.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.models.mac import normalizar_mac


class EstadoAislamiento(Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


def nuevo_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class AccionAislamiento:
    mac_objetivo: str
    fecha_inicio: datetime
    autorizado_por: str
    estado: EstadoAislamiento = EstadoAislamiento.ACTIVO
    fecha_fin: datetime | None = None
    # RI-07: toda AccionAislamiento debería identificar la alerta de origen. El
    # módulo Alertas (CU-05) aún no existe, por lo que aquí queda opcional.
    id_alerta_origen: str | None = None
    id_aislamiento: str = field(default_factory=nuevo_id)

    @property
    def activo(self) -> bool:
        return self.estado is EstadoAislamiento.ACTIVO

    def a_dict(self) -> dict:
        return {
            "idAislamiento": self.id_aislamiento,
            "macObjetivo": self.mac_objetivo,
            "idAlertaOrigen": self.id_alerta_origen,
            "fechaInicio": self.fecha_inicio.isoformat(timespec="seconds"),
            "fechaFin": self.fecha_fin.isoformat(timespec="seconds") if self.fecha_fin else None,
            "estado": self.estado.value,
            "autorizadoPor": self.autorizado_por,
        }

    @classmethod
    def desde_dict(cls, datos: dict) -> "AccionAislamiento":
        fin = datos.get("fechaFin")
        return cls(
            id_aislamiento=datos["idAislamiento"],
            mac_objetivo=normalizar_mac(datos["macObjetivo"]),
            id_alerta_origen=datos.get("idAlertaOrigen"),
            fecha_inicio=datetime.fromisoformat(datos["fechaInicio"]),
            fecha_fin=datetime.fromisoformat(fin) if fin else None,
            estado=EstadoAislamiento(datos["estado"]),
            autorizado_por=datos["autorizadoPor"],
        )
