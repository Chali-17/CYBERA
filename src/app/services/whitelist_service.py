"""WhitelistService: consulta y alta en la lista blanca (RF02, CU-04).

Este módulo solo usa el alta desde el escaneo. La gestión completa (edición,
retiro, alta manual e importación) corresponde al módulo Lista blanca.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.models.dispositivo_confiable import DispositivoConfiable, OrigenRegistro, limpiar_alias
from app.models.mac import es_mac_de_dispositivo, normalizar_mac
from infrastructure.interfaces import IWhitelistRepository


class DispositivoYaAutorizadoError(ValueError):
    pass


class WhitelistService:
    def __init__(self, repositorio: IWhitelistRepository,
                 reloj: Callable[[], datetime] = datetime.now) -> None:
        self._repo = repositorio
        self._reloj = reloj

    def autorizados(self) -> dict[str, DispositivoConfiable]:
        return {d.mac: d for d in self._repo.list() if d.activo}

    def esta_autorizado(self, mac: str) -> bool:
        return self._repo.exists(normalizar_mac(mac))

    def autorizar(self, mac: str, alias: str | None = None,
                  origen: OrigenRegistro = OrigenRegistro.ESCANEO) -> DispositivoConfiable:
        mac = normalizar_mac(mac)                       # RI-03
        if not es_mac_de_dispositivo(mac):
            raise ValueError(f"La dirección {mac} no identifica a un dispositivo.")
        if self._repo.exists(mac):                      # RI-02
            raise DispositivoYaAutorizadoError(f"La MAC {mac} ya está en la lista blanca.")
        dispositivo = DispositivoConfiable(
            mac=mac,
            alias=limpiar_alias(alias),
            fecha_autorizacion=self._reloj().replace(microsecond=0),
            origen_registro=origen,
            activo=True,
        )
        self._repo.add(dispositivo)
        return dispositivo
