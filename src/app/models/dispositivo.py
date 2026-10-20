"""PerfilDispositivo (Modelo de datos, 6.1) y observaciones de red.

Los perfiles de este módulo forman un inventario TEMPORAL: viven solo en
memoria y nunca se escriben en disco.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum

from app.models.mac import es_administrada_localmente


class EstadoDispositivo(Enum):
    CONFIABLE = "Confiable"
    DESCONOCIDO = "Desconocido"
    # Definido en RI-04. Solo lo asignará el módulo de defensa activa (Aislamiento);
    # este módulo nunca lo usa.
    AISLADO = "Aislado"


class FuenteObservacion(Enum):
    RESPUESTA_ARP = "Respondió a una solicitud ARP"
    VECINO_ALCANZABLE = "Windows lo confirmó como alcanzable (tabla de vecinos)"
    INTERFAZ_LOCAL = "Es la interfaz de este equipo"


@dataclass(frozen=True)
class ObservacionRed:
    """Evidencia real de presencia: una IP con su MAC, y de dónde se obtuvo."""

    ip: str
    mac: str
    fuente: FuenteObservacion


@dataclass
class PerfilDispositivo:
    mac: str
    ip: str | None
    primera_deteccion: datetime
    ultima_deteccion: datetime
    fabricante: str | None = None
    hostname: str | None = None
    alias: str | None = None
    estado: EstadoDispositivo = EstadoDispositivo.DESCONOCIDO
    fuente: FuenteObservacion | None = None
    es_este_equipo: bool = False
    es_puerta_enlace: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def mac_local(self) -> bool:
        return es_administrada_localmente(self.mac)

    def copia(self) -> "PerfilDispositivo":
        return replace(self, extra=dict(self.extra))
