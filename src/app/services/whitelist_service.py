"""WhitelistService: gestión de la lista blanca (RF02, CU-04).

Alta desde el escaneo (Dispositivos) y gestión del directorio (Lista blanca):
consulta, edición de alias y retiro. La MAC es el identificador del registro y
nunca se modifica. La importación/exportación no forma parte del alcance.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.models.dispositivo_confiable import DispositivoConfiable, OrigenRegistro, limpiar_alias
from app.models.mac import es_mac_de_dispositivo, normalizar_mac
from app.services.reservas_mac import (AUTORIZAR, MacOcupadaError, ReservasPorMac,
                                       coordinador_de_repositorio)
from infrastructure.interfaces import IWhitelistRepository


class DispositivoYaAutorizadoError(ValueError):
    pass


class AutorizacionBloqueadaError(ValueError):
    """La MAC tiene una operación de aislamiento/desbloqueo en curso (H1)."""


class WhitelistService:
    def __init__(self, repositorio: IWhitelistRepository,
                 reloj: Callable[[], datetime] = datetime.now,
                 reservas: ReservasPorMac | None = None) -> None:
        self._repo = repositorio
        self._reloj = reloj
        # Por defecto, el coordinador único de la carpeta de datos (compartido por
        # todos los servicios del proceso sobre esos archivos).
        self._reservas = reservas or coordinador_de_repositorio(repositorio)

    def autorizados(self) -> dict[str, DispositivoConfiable]:
        return {d.mac: d for d in self._repo.list() if d.activo}

    def listar(self) -> list[DispositivoConfiable]:
        """Dispositivos autorizados vigentes, ordenados por fecha de autorización."""
        activos = [d for d in self._repo.list() if d.activo]
        return sorted(activos, key=lambda d: d.fecha_autorizacion, reverse=True)

    def buscar(self, mac: str) -> DispositivoConfiable | None:
        mac = normalizar_mac(mac)
        return next((d for d in self._repo.list() if d.mac == mac and d.activo), None)

    def esta_autorizado(self, mac: str) -> bool:
        return self._repo.exists(normalizar_mac(mac))

    def editar_alias(self, mac: str, alias: str | None) -> DispositivoConfiable:
        """Actualiza el alias del registro existente (no crea uno nuevo, RI-03)."""
        return self._repo.actualizar_alias(normalizar_mac(mac), limpiar_alias(alias))

    def retirar(self, mac: str) -> None:
        """Elimina la autorización. No aísla ni afecta la conectividad del equipo."""
        self._repo.remove(normalizar_mac(mac))

    def autorizar(self, mac: str, alias: str | None = None,
                  origen: OrigenRegistro = OrigenRegistro.ESCANEO) -> DispositivoConfiable:
        mac = normalizar_mac(mac)                       # RI-03
        if not es_mac_de_dispositivo(mac):
            raise ValueError(f"La dirección {mac} no identifica a un dispositivo.")
        alias = limpiar_alias(alias)
        try:
            # Exclusión con AISLAR/DESBLOQUEAR sobre la misma MAC: la autorización
            # no se completa mientras hay una operación de aislamiento en curso.
            with self._reservas.reservar(mac, AUTORIZAR):
                if self._repo.exists(mac):              # RI-02
                    raise DispositivoYaAutorizadoError(f"La MAC {mac} ya está en la lista blanca.")
                dispositivo = DispositivoConfiable(
                    mac=mac,
                    alias=alias,
                    fecha_autorizacion=self._reloj().replace(microsecond=0),
                    origen_registro=origen,
                    activo=True,
                )
                self._repo.add(dispositivo)
                return dispositivo
        except MacOcupadaError as error:
            raise AutorizacionBloqueadaError(
                f"No se autorizó {mac}: {error} La lista blanca no cambió.") from error
