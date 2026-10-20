"""IsolationService: frontera de seguridad del aislamiento (Arquitectura, 9.2).

Orquesta la operación real: valida la MAC, consulta la lista blanca (RI-05),
solicita el aislamiento al motor de red, verifica el resultado con ``status`` y
solo entonces registra la AccionAislamiento. NO simula el aislamiento.

El motor de red de Capa 2 (``INetworkIsolation``) pertenece al módulo de defensa
activa y todavía no está implementado. Mientras no se inyecte un motor real,
``aislar`` informa que la operación no está disponible y no registra nada.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.models.aislamiento import AccionAislamiento
from app.models.mac import es_mac_de_dispositivo, normalizar_mac
from infrastructure.interfaces import (EstadoRed, IIsolationRepository, INetworkIsolation,
                                       IWhitelistRepository)


class AislamientoError(RuntimeError):
    """Base de los errores de aislamiento."""


class AislamientoNoDisponibleError(AislamientoError):
    """No hay un motor de red capaz de ejecutar el aislamiento."""


class DispositivoProtegidoError(AislamientoError):
    """La MAC está autorizada en la lista blanca (RI-05): no puede aislarse."""


class AislamientoFallidoError(AislamientoError):
    """El motor no confirmó el aislamiento del dispositivo."""


class IsolationService:
    def __init__(self, repositorio: IIsolationRepository, lista_blanca: IWhitelistRepository,
                 motor: INetworkIsolation | None = None,
                 reloj: Callable[[], datetime] = datetime.now) -> None:
        self._repo = repositorio
        self._lista_blanca = lista_blanca
        self._motor = motor
        self._reloj = reloj

    @property
    def disponible(self) -> bool:
        """True solo si hay un motor de red real conectado."""
        return self._motor is not None

    def macs_aisladas(self) -> set[str]:
        return self._repo.macs_activas()

    def aislar(self, mac: str, autorizado_por: str, id_alerta: str | None = None) -> AccionAislamiento:
        try:
            mac = normalizar_mac(mac)                               # RI-03
        except ValueError as error:
            raise AislamientoError(str(error)) from error
        if not es_mac_de_dispositivo(mac):
            raise AislamientoError(
                f"La dirección {mac} no identifica a un dispositivo aislable (difusión o nula).")
        if self._lista_blanca.exists(mac):                          # RI-05
            raise DispositivoProtegidoError(
                f"La MAC {mac} está autorizada en la lista blanca; no se aísla (RI-05).")
        if self._motor is None:
            raise AislamientoNoDisponibleError(
                "El aislamiento no está disponible: falta el motor de red de Capa 2 "
                "(NetworkIsolationEngine), que pertenece al módulo de defensa activa y "
                "requiere privilegios de administrador. No se marcó el dispositivo como aislado.")

        self._motor.isolate(mac)
        if self._motor.status(mac) is not EstadoRed.AISLADO:        # Verificación real.
            raise AislamientoFallidoError(
                f"El motor de red no confirmó el aislamiento de {mac}. "
                "No se marcó el dispositivo como aislado.")
        accion = AccionAislamiento(mac_objetivo=mac, id_alerta_origen=id_alerta,
                                   fecha_inicio=self._reloj().replace(microsecond=0),
                                   autorizado_por=autorizado_por)
        self._repo.crear(accion)
        return accion
