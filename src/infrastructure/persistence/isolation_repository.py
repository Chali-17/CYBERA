"""Repositorio de aislamientos en aislamientos.json (Modelo de datos, 4.1).

Conserva dos colecciones relacionadas en un único archivo:

- ``aislamientos``: contenciones (AccionAislamiento). Un registro ACTIVO es un
  dato ADMINISTRATIVO: el motor la confirmó en su momento. No prueba que siga
  aplicada hoy (ver ``IsolationService.verificar_registrados``). Es la fuente
  de verdad para excluir dispositivos de la pantalla Dispositivos.
- ``operaciones``: solicitudes de aislamiento/desbloqueo (OperacionAislamiento)
  en estado REQUESTED, CONFIRMED o FAILED, incluidos los fallos.

Ambas viven en el mismo archivo para que «operación confirmada» y «contención
creada/finalizada» se escriban en UNA sola escritura atómica. No se guarda ningún
dato del inventario temporal (IP, nombre, fabricante).

Formato 2: ``{"version": 2, "aislamientos": [...], "operaciones": [...]}``.

- El formato 1 se sigue leyendo. Antes de reescribirlo como 2 se crea una copia
  exacta ``aislamientos.json.v1.bak`` (o ``.v1.N.bak`` si ya existe una; nunca
  se sobrescribe). Si la copia falla, no se migra.
- ``version`` debe ser un entero conocido; ``true`` u otros tipos se rechazan.
- Al leer y antes de escribir se valida la coherencia entre colecciones; un
  archivo contradictorio no se usa ni se sobrescribe.
"""

from __future__ import annotations

import dataclasses
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.models.aislamiento import AccionAislamiento, EstadoAislamiento
from app.models.mac import normalizar_mac
from app.models.operacion_aislamiento import (EstadoOperacion, MotivoFallo, OperacionAislamiento,
                                              TipoOperacion)
from infrastructure.interfaces import IIsolationRepository
from infrastructure.persistence.json_file import ArchivoDatosError, JsonFile

VERSION_FORMATO = 2
VERSIONES_LEGIBLES = frozenset({1, 2})


class IncoherenciaError(ValueError):
    """Las colecciones de aislamientos.json se contradicen."""


class JsonIsolationRepository(IIsolationRepository):
    def __init__(self, ruta: Path) -> None:
        self._archivo = JsonFile(ruta)

    @property
    def ruta(self) -> Path:
        return self._archivo.ruta

    # --- Lectura / escritura ------------------------------------------------------

    def _invalido(self, motivo: str) -> ArchivoDatosError:
        return ArchivoDatosError(f"El archivo «{self.ruta}» {motivo} y no se modificó.")

    def _leer(self) -> tuple[list[AccionAislamiento], list[OperacionAislamiento], int | None]:
        """Devuelve (contenciones, operaciones, versión en disco o None si no existe)."""
        datos = self._archivo.leer()
        if datos is None:
            return [], [], None
        if not isinstance(datos, dict) or not isinstance(datos.get("aislamientos"), list):
            raise self._invalido("no tiene la estructura esperada")
        version = datos.get("version", 1)
        # type() y no isinstance(): bool es subclase de int y True == 1 (H5).
        if type(version) is not int or version not in VERSIONES_LEGIBLES:
            raise self._invalido(f"usa un formato desconocido (versión {version!r})")
        operaciones = datos.get("operaciones", [])
        if not isinstance(operaciones, list):
            raise self._invalido("tiene una lista de operaciones inválida")
        try:
            acciones = [AccionAislamiento.desde_dict(d) for d in datos["aislamientos"]]
            ops = [OperacionAislamiento.desde_dict(d) for d in operaciones]
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise self._invalido(f"contiene un registro inválido ({error})") from error
        try:
            validar_coherencia(acciones, ops)
        except IncoherenciaError as error:
            raise self._invalido(f"contiene registros contradictorios ({error})") from error
        return acciones, ops, version

    def _guardar(self, acciones: list[AccionAislamiento], operaciones: list[OperacionAislamiento],
                 version_en_disco: int | None) -> None:
        validar_coherencia(acciones, operaciones)        # Nunca se escribe algo contradictorio.
        if version_en_disco is not None and version_en_disco < VERSION_FORMATO:
            self._respaldar(version_en_disco)
        self._archivo.escribir({
            "version": VERSION_FORMATO,
            "aislamientos": [a.a_dict() for a in acciones],
            "operaciones": [o.a_dict() for o in operaciones],
        })

    def _respaldar(self, version: int) -> Path:
        """Copia exacta del archivo antes de migrarlo (H6). No sobrescribe copias."""
        try:
            contenido = self.ruta.read_bytes()
            for n in range(1000):
                sufijo = f".v{version}.bak" if n == 0 else f".v{version}.{n}.bak"
                destino = self.ruta.with_name(self.ruta.name + sufijo)
                try:
                    with destino.open("xb") as copia:      # «x»: falla si ya existe
                        copia.write(contenido)
                        copia.flush()
                        os.fsync(copia.fileno())
                    return destino
                except FileExistsError:
                    continue
            raise OSError("demasiadas copias de respaldo previas")
        except OSError as error:
            raise ArchivoDatosError(
                f"No se pudo crear la copia de respaldo de «{self.ruta}» antes de migrarlo "
                f"al formato {VERSION_FORMATO} ({error}); no se modificó.") from error

    # --- Contenciones ---------------------------------------------------------------

    def activos(self) -> list[AccionAislamiento]:
        with self._archivo.lock:
            return [a for a in self._leer()[0] if a.activo]

    def macs_activas(self) -> set[str]:
        return {a.mac_objetivo for a in self.activos()}

    def crear(self, accion: AccionAislamiento) -> None:
        """SOLO PRUEBAS / COMPATIBILIDAD (H8). No forma parte de IIsolationRepository
        y ningún módulo de ``src`` debe llamarlo (lo comprueba una prueba). Una
        contención real solo nace con ``resolver`` y una operación CONFIRMED,
        es decir, a través de IsolationService y del motor."""
        with self._archivo.lock:
            acciones, ops, version = self._leer()
            self._agregar_contencion(acciones, accion)
            self._guardar(acciones, ops, version)

    def finalizar(self, mac: str, fecha_fin: datetime) -> None:
        """SOLO PRUEBAS / COMPATIBILIDAD (H8). Ver ``crear``. RI-08: solo finaliza
        aislamientos ACTIVO; se rechaza si hay un desbloqueo en curso."""
        mac = normalizar_mac(mac)
        with self._archivo.lock:
            acciones, ops, version = self._leer()
            self._guardar(_finalizar(acciones, mac, fecha_fin), ops, version)

    @staticmethod
    def _agregar_contencion(acciones: list[AccionAislamiento], accion: AccionAislamiento) -> None:
        if any(a.mac_objetivo == accion.mac_objetivo and a.activo for a in acciones):
            raise ValueError(f"La MAC {accion.mac_objetivo} ya tiene un aislamiento activo.")
        acciones.append(accion)

    # --- Operaciones ----------------------------------------------------------------

    def operaciones(self, mac: str | None = None) -> list[OperacionAislamiento]:
        with self._archivo.lock:
            ops = self._leer()[1]
        if mac is None:
            return ops
        mac = normalizar_mac(mac)
        return [o for o in ops if o.mac_objetivo == mac]

    def registrar_solicitud(self, operacion: OperacionAislamiento) -> None:
        if operacion.estado is not EstadoOperacion.REQUESTED:
            raise ValueError("Solo se registran solicitudes en estado REQUESTED.")
        mac = operacion.mac_objetivo
        with self._archivo.lock:
            acciones, ops, version = self._leer()
            if any(o.mac_objetivo == mac and o.en_curso for o in ops):
                raise ValueError(f"La MAC {mac} ya tiene una operación en curso.")
            activa = next((a for a in acciones if a.mac_objetivo == mac and a.activo), None)
            if operacion.tipo is TipoOperacion.AISLAR and activa is not None:
                raise ValueError(f"La MAC {mac} ya tiene un aislamiento activo.")
            if operacion.tipo is TipoOperacion.DESBLOQUEAR:
                if operacion.id_aislamiento is None:
                    # Desbloqueo de RECUPERACIÓN: solo sin contención registrada y
                    # con una operación de resultado incierto pendiente.
                    if activa is not None or not any(
                            o.mac_objetivo == mac and o.requiere_recuperacion for o in ops):
                        raise ValueError(f"La MAC {mac} no está pendiente de recuperación.")
                elif activa is None or activa.id_aislamiento != operacion.id_aislamiento:
                    raise ValueError(f"La MAC {mac} no tiene el aislamiento activo indicado.")
            self._guardar(acciones, ops + [operacion], version)

    def resolver(self, operacion: OperacionAislamiento,
                 contencion: AccionAislamiento | None = None) -> None:
        if not operacion.terminal:
            raise ValueError("Solo se registra el resultado terminal de una operación.")
        confirmada = operacion.estado is EstadoOperacion.CONFIRMED
        crea = confirmada and operacion.tipo is TipoOperacion.AISLAR
        if (contencion is not None) != crea:
            raise ValueError("Solo un AISLAR confirmado crea una contención.")
        if crea and (contencion.mac_objetivo != operacion.mac_objetivo
                     or contencion.id_aislamiento != operacion.id_aislamiento):
            raise ValueError("La contención no corresponde a la operación confirmada.")
        with self._archivo.lock:
            acciones, ops, version = self._leer()
            indice = next((i for i, o in enumerate(ops)
                           if o.id_operacion == operacion.id_operacion and o.en_curso), None)
            if indice is None:
                raise ValueError("La operación no está registrada como en curso.")
            ops = ops[:indice] + [operacion] + ops[indice + 1:]
            if crea:
                self._agregar_contencion(acciones, contencion)
            elif confirmada and operacion.id_aislamiento is not None:   # DESBLOQUEAR
                antes = acciones
                acciones = _finalizar(acciones, operacion.mac_objetivo,
                                      operacion.fecha_resolucion,
                                      id_aislamiento=operacion.id_aislamiento)
                if acciones == antes:
                    raise ValueError("No existe el aislamiento activo que se pretende finalizar.")
            if confirmada:
                # Un resultado verificado resuelve las incertidumbres previas de la MAC.
                ops = [o.recuperada_por(operacion.id_operacion)
                       if o.mac_objetivo == operacion.mac_objetivo and o.requiere_recuperacion
                       else o for o in ops]
            self._guardar(acciones, ops, version)

    def marcar_interrumpidas(self, fecha: datetime,
                             mac: str | None = None) -> list[OperacionAislamiento]:
        mac = normalizar_mac(mac) if mac is not None else None
        with self._archivo.lock:
            acciones, ops, version = self._leer()
            marcadas: list[OperacionAislamiento] = []
            nuevas = []
            for o in ops:
                if o.en_curso and (mac is None or o.mac_objetivo == mac):
                    o = o.marcar_incierta(
                        MotivoFallo.INTERRUMPIDA, fecha,
                        "La aplicación no llegó a registrar el resultado del motor. "
                        "El estado de contención es desconocido; requiere recuperación.")
                    marcadas.append(o)
                nuevas.append(o)
            if marcadas:
                self._guardar(acciones, nuevas, version)
            return marcadas

    def descartar(self, mac: str) -> None:
        """(Manual) Descarta una situación de aislamiento para una MAC.

        Elimina el aislamiento activo y las operaciones/resoluciones pendientes de
        esa MAC, de modo que deje de figurar como aislado y el escaneo pueda volver a
        detectar al equipo. Es una acción de operador sobre un estado «Requiere
        recuperación» bloqueado; no reintenta automáticamente el desbloqueo.
        """
        mac_objetivo = normalizar_mac(mac)
        with self._archivo.lock:
            acciones, ops, version = self._leer()
            nuevas_acciones = [a for a in acciones
                               if not (a.mac_objetivo == mac_objetivo and a.activo)]
            nuevas_ops = [o for o in ops if o.mac_objetivo != mac_objetivo]
            self._guardar(nuevas_acciones, nuevas_ops, version)


def _finalizar(acciones: list[AccionAislamiento], mac: str, fecha_fin: datetime,
               id_aislamiento: str | None = None) -> list[AccionAislamiento]:
    return [dataclasses.replace(a, fecha_fin=fecha_fin, estado=EstadoAislamiento.INACTIVO)
            if a.mac_objetivo == mac and a.activo
            and (id_aislamiento is None or a.id_aislamiento == id_aislamiento)
            else a
            for a in acciones]


def validar_coherencia(acciones: list[AccionAislamiento],
                       operaciones: list[OperacionAislamiento]) -> None:
    """Rechaza registros contradictorios (H7). Lanza ``IncoherenciaError``."""
    def duplicados(valores):
        return sorted(v for v, n in Counter(valores).items() if n > 1)

    if dup := duplicados(a.id_aislamiento for a in acciones):
        raise IncoherenciaError(f"idAislamiento repetido: {dup}")
    if dup := duplicados(o.id_operacion for o in operaciones):
        raise IncoherenciaError(f"idOperacion repetido: {dup}")
    if dup := duplicados(a.mac_objetivo for a in acciones if a.activo):
        raise IncoherenciaError(f"más de un aislamiento ACTIVO para {dup}")
    if dup := duplicados(o.mac_objetivo for o in operaciones if o.en_curso):
        raise IncoherenciaError(f"más de una operación REQUESTED para {dup}")

    por_id = {a.id_aislamiento: a for a in acciones}
    por_operacion = {o.id_operacion: o for o in operaciones}
    activa = {a.mac_objetivo: a for a in acciones if a.activo}
    for a in acciones:
        if a.activo != (a.fecha_fin is None):
            raise IncoherenciaError(f"estado y fechaFin contradictorios en {a.id_aislamiento}")
    for o in operaciones:
        ref = por_id.get(o.id_aislamiento) if o.id_aislamiento else None
        if ref is not None and ref.mac_objetivo != o.mac_objetivo:
            raise IncoherenciaError(f"la operación {o.id_operacion} apunta a otra MAC")
        if o.en_curso and o.tipo is TipoOperacion.AISLAR and o.mac_objetivo in activa:
            raise IncoherenciaError(f"AISLAR en curso con aislamiento ACTIVO para {o.mac_objetivo}")
        if o.en_curso and o.tipo is TipoOperacion.DESBLOQUEAR:
            actual = activa.get(o.mac_objetivo)
            if o.id_aislamiento is None and actual is not None:
                raise IncoherenciaError(f"desbloqueo de recuperación con aislamiento ACTIVO "
                                        f"para {o.mac_objetivo}")
            if o.id_aislamiento is not None and (
                    actual is None or actual.id_aislamiento != o.id_aislamiento):
                raise IncoherenciaError(f"DESBLOQUEAR en curso sin su aislamiento ACTIVO "
                                        f"para {o.mac_objetivo}")
        # Un desbloqueo de recuperación confirmado no apunta a ninguna contención.
        recuperacion = o.tipo is TipoOperacion.DESBLOQUEAR and o.id_aislamiento is None
        if o.estado is EstadoOperacion.CONFIRMED and ref is None and not recuperacion:
            raise IncoherenciaError(f"operación confirmada {o.id_operacion} sin aislamiento")
        if o.id_recuperacion is not None:
            resolutora = por_operacion.get(o.id_recuperacion)
            if (resolutora is None or resolutora.estado is not EstadoOperacion.CONFIRMED
                    or resolutora.mac_objetivo != o.mac_objetivo):
                raise IncoherenciaError(f"idRecuperacion inválido en {o.id_operacion}")
        if (o.estado is EstadoOperacion.CONFIRMED and o.tipo is TipoOperacion.DESBLOQUEAR
                and ref is not None and ref.activo):
            raise IncoherenciaError(f"desbloqueo confirmado con aislamiento aún ACTIVO "
                                    f"({o.mac_objetivo})")
