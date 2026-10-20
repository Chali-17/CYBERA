"""Contratos internos (Arquitectura, sección 15.1).

Los servicios dependen de estas abstracciones; los adaptadores concretos de
Windows y de archivos JSON las implementan. Así, cambiar la técnica de
descubrimiento o el formato de almacenamiento no afecta a la lógica ni a la vista.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from enum import Enum

from app.models.aislamiento import AccionAislamiento
from app.models.configuracion import ConfiguracionSistema
from app.models.dispositivo import ObservacionRed
from app.models.dispositivo_confiable import DispositivoConfiable
from app.models.interfaz_red import InterfazRed


class EstadoRed(Enum):
    """Estado de contención que el motor de red confirma para una MAC."""

    AISLADO = "AISLADO"
    ACTIVO = "ACTIVO"       # Con conectividad normal (no aislado).
    DESCONOCIDO = "DESCONOCIDO"


class INetworkInterface(ABC):
    @abstractmethod
    def list_interfaces(self) -> list[InterfazRed]:
        """Interfaces de red reales que expone el sistema operativo."""


class IArpProbe(ABC):
    """Obtención de pares IP–MAC presentes en el segmento local."""

    @abstractmethod
    def sondear(self, ips: list[str], ip_origen: str,
                cancelar: threading.Event) -> list[ObservacionRed]:
        """Envía solicitudes ARP activas y devuelve las que obtuvieron respuesta."""

    @abstractmethod
    def vecinos_alcanzables(self, indice_interfaz: int) -> list[ObservacionRed]:
        """Entradas de la tabla de vecinos que el sistema confirma como alcanzables."""


class IOuiResolver(ABC):
    @abstractmethod
    def fabricante(self, mac: str) -> str | None:
        """Fabricante registrado para el bloque OUI de la MAC, o None."""


class IHostnameResolver(ABC):
    @abstractmethod
    def resolver(self, ip: str) -> str | None:
        """Nombre de host de la IP, o None si no se puede resolver."""


class IWhitelistRepository(ABC):
    @abstractmethod
    def exists(self, mac: str) -> bool: ...

    @abstractmethod
    def add(self, dispositivo: DispositivoConfiable) -> None: ...

    @abstractmethod
    def remove(self, mac: str) -> None: ...

    @abstractmethod
    def list(self) -> list[DispositivoConfiable]: ...


class ISettingsRepository(ABC):
    @abstractmethod
    def load(self) -> ConfiguracionSistema: ...

    @abstractmethod
    def save(self, configuracion: ConfiguracionSistema) -> None: ...


class IIsolationRepository(ABC):
    """Persistencia de las acciones de aislamiento (aislamientos.json)."""

    @abstractmethod
    def crear(self, accion: AccionAislamiento) -> None: ...

    @abstractmethod
    def finalizar(self, mac: str, fecha_fin) -> None: ...

    @abstractmethod
    def activos(self) -> list[AccionAislamiento]: ...

    @abstractmethod
    def macs_activas(self) -> set[str]: ...


class INetworkIsolation(ABC):
    """Motor de red de Capa 2 (Arquitectura, 10.2). Encapsula la técnica real
    de aislamiento. Requiere privilegios elevados y acceso a la red.
    """

    @abstractmethod
    def isolate(self, mac: str) -> None: ...

    @abstractmethod
    def release(self, mac: str) -> None: ...

    @abstractmethod
    def status(self, mac: str) -> "EstadoRed": ...
