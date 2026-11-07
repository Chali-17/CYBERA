"""Exclusión mutua por MAC compartida entre servicios (corrección H1).

IsolationService (AISLAR / DESBLOQUEAR) y WhitelistService (AUTORIZAR) obtienen
la MISMA instancia de ``ReservasPorMac`` por carpeta de datos
(``coordinador_para``), aunque se construyan por separado. Así una
autorización no puede completarse mientras hay un aislamiento en curso sobre la
misma MAC, ni un aislamiento puede empezar mientras se autoriza esa MAC.

- No bloqueante: si la MAC está ocupada se lanza ``MacOcupadaError`` al instante
  (no se encola), lo que evita duplicados y esperas en el hilo de la interfaz.
- MAC distintas no comparten reserva.
- La reserva se libera en ``finally``, también ante excepciones.
- Solo coordina hilos de UN proceso. Entre procesos, la protección es la
  instancia única (``infrastructure/instancia_unica.py``).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

AISLAR = "AISLAR"
DESBLOQUEAR = "DESBLOQUEAR"
AUTORIZAR = "AUTORIZAR"
VERIFICAR = "VERIFICAR"

NOMBRES = {AISLAR: "aislamiento", DESBLOQUEAR: "desbloqueo", AUTORIZAR: "autorización",
           VERIFICAR: "verificación"}


class MacOcupadaError(RuntimeError):
    def __init__(self, mac: str, operacion: str) -> None:
        super().__init__(f"Ya hay una operación de {NOMBRES.get(operacion, operacion)} en curso "
                         f"para {mac}. Espere a que termine.")
        self.mac = mac
        self.operacion = operacion


class ReservasPorMac:
    def __init__(self) -> None:
        self._candado = threading.Lock()
        self._ocupadas: dict[str, str] = {}

    @contextmanager
    def reservar(self, mac: str, operacion: str) -> Iterator[None]:
        with self._candado:
            actual = self._ocupadas.get(mac)
            if actual is not None:
                raise MacOcupadaError(mac, actual)
            self._ocupadas[mac] = operacion
        try:
            yield
        finally:
            with self._candado:
                self._ocupadas.pop(mac, None)

    def en_curso(self, mac: str) -> str | None:
        with self._candado:
            return self._ocupadas.get(mac)

    def ocupadas(self) -> dict[str, str]:
        with self._candado:
            return dict(self._ocupadas)


# --- Coordinador único por carpeta de datos -------------------------------------
# Todos los servicios del proceso que trabajan sobre la MISMA carpeta de datos
# reciben la MISMA instancia, aunque se construyan por separado. Así dos
# IsolationService (o un IsolationService y un WhitelistService) sobre los mismos
# archivos nunca ejecutan operaciones incompatibles a la vez.

_coordinadores: dict[str, ReservasPorMac] = {}
_candado_coordinadores = threading.Lock()


def _clave(directorio) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(directorio)))


def coordinador_para(directorio) -> ReservasPorMac:
    with _candado_coordinadores:
        return _coordinadores.setdefault(_clave(directorio), ReservasPorMac())


def coordinador_de_repositorio(repositorio) -> ReservasPorMac:
    """Coordinador de la carpeta del archivo del repositorio (atributo ``ruta``).
    Un repositorio sin archivo (doble de prueba) recibe un coordinador propio."""
    ruta = getattr(repositorio, "ruta", None)
    if ruta is None:
        return ReservasPorMac()
    return coordinador_para(Path(ruta).parent)
