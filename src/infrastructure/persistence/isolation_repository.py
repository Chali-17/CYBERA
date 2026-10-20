"""Repositorio de aislamientos en aislamientos.json (Modelo de datos, 4.1).

Conserva las contenciones activas y el historial de finalización. Una MAC solo
figura como aislada si existe aquí un registro con estado ACTIVO; esta es la
fuente de verdad para excluir dispositivos aislados de la pantalla Dispositivos.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.models.aislamiento import AccionAislamiento, EstadoAislamiento
from app.models.mac import normalizar_mac
from infrastructure.interfaces import IIsolationRepository
from infrastructure.persistence.json_file import ArchivoDatosError, JsonFile

VERSION_FORMATO = 1


class JsonIsolationRepository(IIsolationRepository):
    """Estructura: ``{"version": 1, "aislamientos": [AccionAislamiento, ...]}``."""

    def __init__(self, ruta: Path) -> None:
        self._archivo = JsonFile(ruta)

    @property
    def ruta(self) -> Path:
        return self._archivo.ruta

    def _leer_todos(self) -> list[AccionAislamiento]:
        datos = self._archivo.leer()
        if datos is None:
            return []
        if not isinstance(datos, dict) or not isinstance(datos.get("aislamientos"), list):
            raise ArchivoDatosError(
                f"El archivo «{self.ruta}» no tiene la estructura esperada y no se modificó.")
        try:
            return [AccionAislamiento.desde_dict(d) for d in datos["aislamientos"]]
        except (KeyError, TypeError, ValueError) as error:
            raise ArchivoDatosError(
                f"El archivo «{self.ruta}» contiene un registro inválido ({error}) "
                f"y no se modificó.") from error

    def _guardar_todos(self, acciones: list[AccionAislamiento]) -> None:
        self._archivo.escribir({
            "version": VERSION_FORMATO,
            "aislamientos": [a.a_dict() for a in acciones],
        })

    def activos(self) -> list[AccionAislamiento]:
        with self._archivo.lock:
            return [a for a in self._leer_todos() if a.activo]

    def macs_activas(self) -> set[str]:
        return {a.mac_objetivo for a in self.activos()}

    def crear(self, accion: AccionAislamiento) -> None:
        with self._archivo.lock:
            actuales = self._leer_todos()
            if any(a.mac_objetivo == accion.mac_objetivo and a.activo for a in actuales):
                raise ValueError(f"La MAC {accion.mac_objetivo} ya tiene un aislamiento activo.")
            self._guardar_todos(actuales + [accion])

    def finalizar(self, mac: str, fecha_fin: datetime) -> None:
        """RI-08: solo finaliza aislamientos que estén ACTIVO."""
        mac = normalizar_mac(mac)
        with self._archivo.lock:
            actuales = self._leer_todos()
            nuevos = []
            for a in actuales:
                if a.mac_objetivo == mac and a.activo:
                    nuevos.append(AccionAislamiento(
                        id_aislamiento=a.id_aislamiento, mac_objetivo=a.mac_objetivo,
                        id_alerta_origen=a.id_alerta_origen, fecha_inicio=a.fecha_inicio,
                        fecha_fin=fecha_fin, estado=EstadoAislamiento.INACTIVO,
                        autorizado_por=a.autorizado_por))
                else:
                    nuevos.append(a)
            self._guardar_todos(nuevos)
