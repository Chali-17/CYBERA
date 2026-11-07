"""EventoBitacora (Modelo de datos, módulo Bitácora).

Un evento resume una situación relevante del sistema: aparición o desaparición
de un dispositivo en la red, autorización de un dispositivo o resultado de un
aislamiento/desbloqueo. Cada evento lleva su identificador único, la fecha y
hora exactas, el tipo, los datos disponibles del dispositivo y el resultado de
la operación cuando corresponde.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

LONGITUD_MAXIMA_DESCRIPCION = 300


class TipoEvento(Enum):
    CONEXION = "CONEXION"
    DESCONEXION = "DESCONEXION"
    BLOQUEO = "BLOQUEO"
    DESBLOQUEO = "DESBLOQUEO"
    AUTORIZACION_DISPOSITIVO = "AUTORIZACION_DISPOSITIVO"


class ResultadoEvento(Enum):
    EXITOSO = "EXITOSO"
    FALLO = "FALLO"


def nuevo_id() -> str:
    return str(uuid.uuid4())


def _recortar(texto: str | None) -> str | None:
    if texto is None:
        return None
    texto = " ".join(str(texto).split())
    return texto[:LONGITUD_MAXIMA_DESCRIPCION] or None


@dataclass(frozen=True)
class EventoBitacora:
    """Registro del historial de eventos. ``mac_dispositivo`` es el identificador
    del dispositivo cuando existe; la MAC nula o ausente se usa para eventos sin
    dispositivo asociado."""

    id: str
    tipo: TipoEvento
    fecha_hora: datetime
    mac_dispositivo: str | None = None
    ip_dispositivo: str | None = None
    nombre_dispositivo: str | None = None
    descripcion: str | None = None
    resultado: ResultadoEvento | None = None
    actor: str | None = None

    def __post_init__(self) -> None:
        # Normalización única: descripción recortada (y en blanco → None).
        object.__setattr__(self, "descripcion", _recortar(self.descripcion))

    def a_dict(self) -> dict:
        return {
            "id": self.id,
            "tipo": self.tipo.value,
            "fechaHora": self.fecha_hora.isoformat(timespec="seconds"),
            "macDispositivo": self.mac_dispositivo,
            "ipDispositivo": self.ip_dispositivo,
            "nombreDispositivo": self.nombre_dispositivo,
            "descripcion": self.descripcion,
            "resultado": self.resultado.value if self.resultado else None,
            "actor": self.actor,
        }

    @classmethod
    def desde_dict(cls, datos: dict) -> "EventoBitacora":
        tipo = TipoEvento(datos["tipo"])
        resultado = ResultadoEvento(datos["resultado"]) if datos.get("resultado") else None
        actor = datos.get("actor")
        return cls(
            id=datos["id"],
            tipo=tipo,
            fecha_hora=datetime.fromisoformat(datos["fechaHora"]),
            mac_dispositivo=datos.get("macDispositivo"),
            ip_dispositivo=datos.get("ipDispositivo"),
            nombre_dispositivo=datos.get("nombreDispositivo"),
            descripcion=_recortar(datos.get("descripcion")),
            resultado=resultado,
            actor=" ".join(str(actor or "").split()) or None,
        )


# --- Textos legibles (los comparten la vista Bitácora y los reportes) -------------

ETIQUETA_TIPO = {
    TipoEvento.CONEXION: "Conexión",
    TipoEvento.DESCONEXION: "Desconexión",
    TipoEvento.BLOQUEO: "Aislamiento",
    TipoEvento.DESBLOQUEO: "Desbloqueo",
    TipoEvento.AUTORIZACION_DISPOSITIVO: "Autorización",
}

ETIQUETA_RESULTADO = {
    ResultadoEvento.EXITOSO: "Exitoso",
    ResultadoEvento.FALLO: "Fallido",
}
RESULTADO_SIN_OPERACION = "Registrado"


def etiqueta_tipo(tipo: TipoEvento | None) -> str:
    return ETIQUETA_TIPO.get(tipo, "No disponible") if tipo is not None else "No disponible"


def etiqueta_resultado(resultado: ResultadoEvento | None) -> str:
    """Eventos sin operación asociada (conexión, desconexión) se muestran como «Registrado»."""
    return ETIQUETA_RESULTADO[resultado] if resultado is not None else RESULTADO_SIN_OPERACION
