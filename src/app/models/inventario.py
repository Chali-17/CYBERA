"""Inventario temporal de dispositivos detectados (solo en memoria)."""

from __future__ import annotations

import ipaddress
import threading
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from app.models.dispositivo import EstadoDispositivo, PerfilDispositivo


@dataclass
class _Entrada:
    perfil: PerfilDispositivo
    ciclos_sin_observar: int = 0


def _clave_ip(perfil: PerfilDispositivo):
    try:
        return (0, int(ipaddress.ip_address(perfil.ip or "")))
    except ValueError:
        return (1, perfil.mac)


class InventarioTemporal:
    """Dispositivos presentes en la red según los ciclos de descubrimiento.

    Regla de tolerancia: no responder a un ciclo NO significa estar
    desconectado (ahorro de energía, pérdida puntual de paquetes Wi-Fi). Un
    equipo que deja de observarse se mantiene durante ``ciclos_tolerancia``
    ciclos adicionales y después se retira de la lista.

    No tiene ningún mecanismo de persistencia: al cerrar la aplicación se pierde.
    """

    def __init__(self, ciclos_tolerancia: int = 2) -> None:
        if ciclos_tolerancia < 0:
            raise ValueError("ciclos_tolerancia no puede ser negativo")
        self._tolerancia = ciclos_tolerancia
        self._entradas: dict[str, _Entrada] = {}
        self._lock = threading.Lock()

    def actualizar(self, observados: list[PerfilDispositivo], ahora: datetime) -> None:
        with self._lock:
            vistos: set[str] = set()
            for perfil in observados:
                nuevo = perfil.copia()
                anterior = self._entradas.get(nuevo.mac)
                if anterior is not None:
                    nuevo.primera_deteccion = anterior.perfil.primera_deteccion
                nuevo.ultima_deteccion = ahora
                self._entradas[nuevo.mac] = _Entrada(nuevo)
                vistos.add(nuevo.mac)
            for mac in list(self._entradas):
                if mac in vistos:
                    continue
                entrada = self._entradas[mac]
                entrada.ciclos_sin_observar += 1
                if entrada.ciclos_sin_observar > self._tolerancia:
                    del self._entradas[mac]

    def visibles(self, excluidas: Collection[str] = ()) -> list[PerfilDispositivo]:
        """Perfiles detectados cuya MAC NO está en ``excluidas``.

        ``excluidas`` son las MAC autorizadas (lista blanca) y aisladas: la
        pantalla Dispositivos solo muestra lo detectado, no autorizado y no
        aislado. Los perfiles visibles siempre están en estado DESCONOCIDO.
        """
        excluidas = set(excluidas)
        with self._lock:
            perfiles = []
            for mac, entrada in self._entradas.items():
                if mac in excluidas:
                    continue
                perfil = entrada.perfil.copia()
                perfil.estado = EstadoDispositivo.DESCONOCIDO
                perfil.alias = None
                perfiles.append(perfil)
        return sorted(perfiles, key=_clave_ip)

    def macs(self) -> set[str]:
        with self._lock:
            return set(self._entradas)

    def obtener(self, mac: str) -> PerfilDispositivo | None:
        """Perfil detectado para ``mac`` (aunque esté excluido de la tabla), o None."""
        with self._lock:
            entrada = self._entradas.get(mac)
            return entrada.perfil.copia() if entrada is not None else None

    def limpiar(self) -> None:
        with self._lock:
            self._entradas.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entradas)
