"""Interfaz de red del equipo huésped (RF12)."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import Enum

_APIPA = ipaddress.ip_network("169.254.0.0/16")


class TipoInterfaz(Enum):
    """Tipo de interfaz.

    El Modelo de datos define ETHERNET y WIFI. Se añade OTRO porque Windows
    también expone adaptadores Bluetooth, VPN o virtuales y RF12 pide no imponer
    validaciones restrictivas a nivel de hardware.
    """

    ETHERNET = "ETHERNET"
    WIFI = "WIFI"
    OTRO = "OTRO"

    @property
    def etiqueta(self) -> str:
        return {"ETHERNET": "Ethernet", "WIFI": "Wi-Fi", "OTRO": "Otro"}[self.value]


@dataclass(frozen=True)
class InterfazRed:
    id: str                      # InterfaceGuid de Windows (estable entre reinicios)
    indice: int                  # ifIndex de Windows
    nombre: str                  # Nombre visible, p. ej. «Wi-Fi»
    descripcion: str             # Descripción del adaptador
    tipo: TipoInterfaz
    conectada: bool
    mac: str | None = None
    ipv4: str | None = None
    prefijo: int | None = None
    puerta_enlace: str | None = None
    virtual: bool = False

    @property
    def red(self) -> ipaddress.IPv4Network | None:
        if not self.ipv4 or self.prefijo is None:
            return None
        return ipaddress.ip_network(f"{self.ipv4}/{self.prefijo}", strict=False)

    def motivo_no_utilizable(self) -> str | None:
        """Explica por qué no se puede monitorear por esta interfaz, o None."""
        if not self.conectada:
            return f"La interfaz «{self.nombre}» está desconectada."
        if not self.ipv4 or self.prefijo is None:
            return f"La interfaz «{self.nombre}» no tiene una dirección IPv4."
        if ipaddress.ip_address(self.ipv4) in _APIPA:
            return (f"La interfaz «{self.nombre}» solo tiene una dirección automática "
                    f"169.254.x.x; no está conectada a una red con direcciones asignadas.")
        return None

    @property
    def utilizable(self) -> bool:
        return self.motivo_no_utilizable() is None
