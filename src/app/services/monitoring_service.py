"""MonitoringService: ciclo captura → identificación → clasificación (Arquitectura, 9.1).

Mantiene el inventario temporal EN MEMORIA. No escribe dispositivos detectados
en ningún archivo.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from app.models.dispositivo import PerfilDispositivo
from app.models.interfaz_red import InterfazRed
from app.models.inventario import InventarioTemporal
from app.services.device_discovery_service import (DeviceDiscoveryService,
                                                   InterfazNoDisponibleError,
                                                   ResultadoDescubrimiento)
from app.services.network_interface_service import NetworkInterfaceService
from app.services.settings_service import SettingsService
from app.services.whitelist_service import WhitelistService

_log = logging.getLogger(__name__)

# El Modelo de datos no define un intervalo configurable; queda fijo (punto pendiente).
INTERVALO_ESCANEO_S = 30
CICLOS_TOLERANCIA = 2


class FuenteAislamiento(Protocol):
    """Expone las MAC con aislamiento activo (IsolationService lo cumple)."""

    def macs_aisladas(self) -> set[str]: ...


class _SinAislamiento:
    """Objeto nulo: usado cuando no se inyecta un origen de aislamiento."""

    def macs_aisladas(self) -> set[str]:
        return set()


class TipoResultado(Enum):
    ACTUALIZADO = "ACTUALIZADO"
    MONITOREO_INACTIVO = "MONITOREO_INACTIVO"
    SIN_INTERFAZ = "SIN_INTERFAZ"
    INTERFAZ_NO_DISPONIBLE = "INTERFAZ_NO_DISPONIBLE"
    ERROR = "ERROR"
    CANCELADO = "CANCELADO"


@dataclass
class ResultadoCiclo:
    tipo: TipoResultado
    dispositivos: list[PerfilDispositivo] = field(default_factory=list)
    mensaje: str | None = None
    interfaz: InterfazRed | None = None
    detalle: ResultadoDescubrimiento | None = None


class MonitoringService:
    def __init__(self, configuracion: SettingsService, interfaces: NetworkInterfaceService,
                 descubrimiento: DeviceDiscoveryService, lista_blanca: WhitelistService,
                 aislamiento: FuenteAislamiento | None = None,
                 inventario: InventarioTemporal | None = None,
                 reloj: Callable[[], datetime] = datetime.now) -> None:
        self._configuracion = configuracion
        self._interfaces = interfaces
        self._descubrimiento = descubrimiento
        self._lista_blanca = lista_blanca
        self._aislamiento = aislamiento or _SinAislamiento()
        self._inventario = inventario or InventarioTemporal(CICLOS_TOLERANCIA)
        self._reloj = reloj
        self._interfaz_actual: str | None = None
        self._lock = threading.Lock()

    def ejecutar_ciclo(self, cancelar: threading.Event) -> ResultadoCiclo:
        with self._lock:
            return self._ciclo(cancelar)

    def _ciclo(self, cancelar: threading.Event) -> ResultadoCiclo:
        try:
            cfg = self._configuracion.cargar()
        except Exception as error:  # noqa: BLE001
            self._inventario.limpiar()
            return ResultadoCiclo(TipoResultado.ERROR, mensaje=f"No se pudo leer la configuración: {error}")

        if not cfg.monitoreo_activo:
            self._inventario.limpiar()
            return ResultadoCiclo(TipoResultado.MONITOREO_INACTIVO,
                                  mensaje="El monitoreo está inactivo. Actívelo en Configuración.")
        if not cfg.interfaz_id:
            self._inventario.limpiar()
            return ResultadoCiclo(TipoResultado.SIN_INTERFAZ,
                                  mensaje="No hay una interfaz de red seleccionada. Elíjala en Configuración.")
        try:
            interfaz = self._interfaces.buscar(cfg.interfaz_id)
        except Exception as error:  # noqa: BLE001
            self._inventario.limpiar()
            return ResultadoCiclo(TipoResultado.ERROR,
                                  mensaje=f"No se pudieron consultar las interfaces de red: {error}")
        nombre = cfg.nombre_interfaz or cfg.interfaz_id
        if interfaz is None:
            self._inventario.limpiar()
            return ResultadoCiclo(TipoResultado.INTERFAZ_NO_DISPONIBLE, mensaje=(
                f"La interfaz configurada «{nombre}» ya no está presente en el equipo. "
                "No se cambió a otra interfaz. Seleccione una en Configuración."))
        motivo = interfaz.motivo_no_utilizable()
        if motivo:
            self._inventario.limpiar()
            return ResultadoCiclo(TipoResultado.INTERFAZ_NO_DISPONIBLE, interfaz=interfaz, mensaje=(
                f"{motivo} No se realizan escaneos y no se cambió a otra interfaz."))

        if interfaz.id != self._interfaz_actual:
            self._inventario.limpiar()   # Otra red: lo anterior ya no aplica.
            self._interfaz_actual = interfaz.id

        try:
            detalle = self._descubrimiento.descubrir(interfaz, cancelar)
        except InterfazNoDisponibleError as error:
            self._inventario.limpiar()
            return ResultadoCiclo(TipoResultado.INTERFAZ_NO_DISPONIBLE, interfaz=interfaz, mensaje=str(error))
        except Exception as error:  # noqa: BLE001
            _log.exception("Fallo del descubrimiento")
            self._inventario.limpiar()
            return ResultadoCiclo(TipoResultado.ERROR, interfaz=interfaz,
                                  mensaje=f"El descubrimiento de dispositivos falló: {error}")
        if detalle.cancelado or cancelar.is_set():
            return ResultadoCiclo(TipoResultado.CANCELADO, interfaz=interfaz)

        self._inventario.actualizar(detalle.perfiles, self._reloj().replace(microsecond=0))
        try:
            visibles = self._filtrar()
        except Exception as error:  # noqa: BLE001
            self._inventario.limpiar()
            return ResultadoCiclo(TipoResultado.ERROR, interfaz=interfaz, mensaje=(
                f"No se pudo leer la lista blanca o el registro de aislamiento, por lo que "
                f"no es posible decidir qué dispositivos mostrar: {error}"))
        return ResultadoCiclo(TipoResultado.ACTUALIZADO, dispositivos=visibles,
                              interfaz=interfaz, detalle=detalle)

    def _filtrar(self) -> list[PerfilDispositivo]:
        """visible = detectado − autorizado − aislado (fuente de verdad: repositorios)."""
        excluidas = set(self._lista_blanca.autorizados()) | self._aislamiento.macs_aisladas()
        return self._inventario.visibles(excluidas)

    def reclasificar(self) -> list[PerfilDispositivo]:
        """Recalcula la lista visible desde el inventario y los repositorios, sin escanear."""
        return self._filtrar()

    def detener(self) -> None:
        """Descarta el inventario temporal (monitoreo desactivado o cierre)."""
        self._inventario.limpiar()
        self._interfaz_actual = None
