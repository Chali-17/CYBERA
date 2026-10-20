"""NetworkInterfaceService (Arquitectura, sección 10): interfaces disponibles."""

from __future__ import annotations

from app.models.interfaz_red import InterfazRed
from infrastructure.interfaces import INetworkInterface


class NetworkInterfaceService:
    def __init__(self, proveedor: INetworkInterface) -> None:
        self._proveedor = proveedor

    def listar(self) -> list[InterfazRed]:
        """Interfaces del sistema; primero las conectadas y utilizables."""
        interfaces = self._proveedor.list_interfaces()
        return sorted(interfaces, key=lambda i: (not i.utilizable, i.virtual, i.nombre.lower()))

    def buscar(self, interfaz_id: str) -> InterfazRed | None:
        """Interfaz con ese identificador exacto. Nunca sustituye por otra."""
        for interfaz in self._proveedor.list_interfaces():
            if interfaz.id == interfaz_id:
                return interfaz
        return None
