"""OperacionAislamiento: máquina de estados de una solicitud de aislamiento o desbloqueo.

Se separan tres conceptos que NO deben mezclarse en un único campo:

1. Autorización  → ``lista_blanca.json`` (DispositivoConfiable). Fuente de verdad
   de los dispositivos autorizados. Este módulo solo la consulta.
2. Operación     → ``OperacionAislamiento`` (este archivo). Una solicitud
   explícita del usuario (AISLAR o DESBLOQUEAR) y su ciclo de vida.
3. Contención    → ``AccionAislamiento`` (ACTIVO/INACTIVO). El aislamiento que el
   motor de red CONFIRMÓ. Solo se crea o finaliza cuando una operación llega a
   CONFIRMED.

Estados de una operación (por MAC normalizada)::

    PENDING ──► REQUESTED ──► CONFIRMED
       │            ├──────► UNCERTAIN   (resultado de red desconocido)
       └──► FAILED ◄┘

- PENDING:   creada en memoria tras validar la solicitud. Aún no se envió nada
             al motor ni se escribió en disco.
- REQUESTED: la solicitud quedó registrada en aislamientos.json (registro previo
             al envío) y se entregó al motor. NO equivale a éxito.
- CONFIRMED: ``status`` devolvió el ``EstadoContencion`` exigido por el contrato
             (CONTENCION_APLICADA para AISLAR, SIN_CONTENCION para DESBLOQUEAR).
- FAILED:    la operación no se completó y su efecto de red es CONOCIDO: no se
             envió nada, el motor garantizó que no modificó nada, o ``status``
             devolvió un valor del contrato que contradice lo pedido.
- UNCERTAIN: la orden pudo llegar al motor, pero no se sabe qué dejó aplicado
             (error del motor, ``status`` desconocido o inválido, cierre a mitad
             o reversión fallida). REQUIERE RECUPERACIÓN.

CONFIRMED, FAILED y UNCERTAIN son terminales. Cualquier otra transición se
rechaza con ``TransicionInvalidaError``.

Recuperación: una operación UNCERTAIN deja la MAC «pendiente de recuperación»
hasta que una operación POSTERIOR sobre la misma MAC llegue a CONFIRMED (es la
única evidencia verificada). Esa operación queda enlazada en ``id_recuperacion``.
Nunca se reintenta nada automáticamente: la recuperación es una acción explícita
del usuario («Desbloquear» en la pantalla Aislamiento).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.models.aislamiento import nuevo_id
from app.models.mac import normalizar_mac

LONGITUD_MAXIMA_DETALLE = 300


class TipoOperacion(Enum):
    AISLAR = "AISLAR"
    DESBLOQUEAR = "DESBLOQUEAR"


class EstadoOperacion(Enum):
    PENDING = "PENDING"
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


class MotivoFallo(Enum):
    # Sin envío al motor (PENDING → FAILED):
    NO_DISPONIBLE = "NO_DISPONIBLE"          # No hay motor de red o no está operativo.
    ERROR_REGISTRO = "ERROR_REGISTRO"        # No se pudo registrar la solicitud en disco.
    # Tras REQUESTED:
    ERROR_MOTOR = "ERROR_MOTOR"              # El motor lanzó un error.
    SIN_CONFIRMACION = "SIN_CONFIRMACION"    # status() no devolvió el estado exigido.
    INTERRUMPIDA = "INTERRUMPIDA"            # La aplicación se cerró sin registrar el resultado.
    AUTORIZADA = "AUTORIZADA"                # La MAC pasó a estar autorizada (RI-05).
    AUTORIZACION_NO_VERIFICABLE = "AUTORIZACION_NO_VERIFICABLE"  # Lista blanca ilegible.
    REVERSION_FALLIDA = "REVERSION_FALLIDA"  # No se verificó la reversión de una contención.


MOTIVOS_SIN_ENVIO = frozenset({MotivoFallo.NO_DISPONIBLE, MotivoFallo.ERROR_REGISTRO})
# REQUESTED → FAILED: el efecto de red es conocido.
MOTIVOS_FALLO_CONOCIDO = frozenset({
    MotivoFallo.ERROR_MOTOR,                 # Solo con OperacionNoEjecutadaError del motor.
    MotivoFallo.SIN_CONFIRMACION,            # status() contradictorio pero válido.
    MotivoFallo.AUTORIZADA, MotivoFallo.AUTORIZACION_NO_VERIFICABLE})
# REQUESTED → UNCERTAIN: el efecto de red es desconocido.
MOTIVOS_INCIERTOS = frozenset({MotivoFallo.ERROR_MOTOR, MotivoFallo.SIN_CONFIRMACION,
                               MotivoFallo.INTERRUMPIDA, MotivoFallo.REVERSION_FALLIDA})
# Compatibilidad: nombre usado antes de existir UNCERTAIN.
MOTIVOS_TRAS_ENVIO = MOTIVOS_FALLO_CONOCIDO | MOTIVOS_INCIERTOS

# Transiciones permitidas. Todo lo que no figura aquí se rechaza.
TRANSICIONES: dict[EstadoOperacion, frozenset[EstadoOperacion]] = {
    EstadoOperacion.PENDING: frozenset({EstadoOperacion.REQUESTED, EstadoOperacion.FAILED}),
    EstadoOperacion.REQUESTED: frozenset({EstadoOperacion.CONFIRMED, EstadoOperacion.FAILED,
                                          EstadoOperacion.UNCERTAIN}),
    EstadoOperacion.CONFIRMED: frozenset(),
    EstadoOperacion.FAILED: frozenset(),
    EstadoOperacion.UNCERTAIN: frozenset(),
}

# Estados que pueden figurar en aislamientos.json. PENDING vive solo en memoria.
ESTADOS_PERSISTIBLES = frozenset({EstadoOperacion.REQUESTED, EstadoOperacion.CONFIRMED,
                                  EstadoOperacion.FAILED, EstadoOperacion.UNCERTAIN})
_ESTADOS_CON_MOTIVO = frozenset({EstadoOperacion.FAILED, EstadoOperacion.UNCERTAIN})


class TransicionInvalidaError(ValueError):
    """Se intentó una transición que la máquina de estados no permite."""


def _recortar(texto: str | None) -> str | None:
    if texto is None:
        return None
    texto = " ".join(str(texto).split())
    return texto[:LONGITUD_MAXIMA_DETALLE] or None


@dataclass(frozen=True)
class OperacionAislamiento:
    mac_objetivo: str
    tipo: TipoOperacion
    solicitado_por: str
    fecha_solicitud: datetime
    estado: EstadoOperacion = EstadoOperacion.PENDING
    fecha_resolucion: datetime | None = None
    motivo_fallo: MotivoFallo | None = None
    detalle: str | None = None
    # Contención afectada: la creada (AISLAR confirmado) o la que se pretende
    # finalizar (DESBLOQUEAR). None si no aplica (p. ej. desbloqueo de recuperación).
    id_aislamiento: str | None = None
    id_operacion: str = field(default_factory=nuevo_id)
    # Solo en operaciones con resultado incierto: la operación CONFIRMED posterior
    # que dejó verificada la situación de la MAC.
    id_recuperacion: str | None = None

    @property
    def terminal(self) -> bool:
        return not TRANSICIONES[self.estado]

    @property
    def en_curso(self) -> bool:
        return self.estado is EstadoOperacion.REQUESTED

    @property
    def resultado_incierto(self) -> bool:
        """El efecto de red de esta operación es desconocido. Incluye los
        FAILED/INTERRUMPIDA escritos antes de existir UNCERTAIN."""
        return (self.estado is EstadoOperacion.UNCERTAIN
                or (self.estado is EstadoOperacion.FAILED
                    and self.motivo_fallo is MotivoFallo.INTERRUMPIDA))

    @property
    def requiere_recuperacion(self) -> bool:
        return self.resultado_incierto and self.id_recuperacion is None

    # --- Transiciones -----------------------------------------------------------

    def _pasar_a(self, destino: EstadoOperacion, **cambios) -> "OperacionAislamiento":
        if destino not in TRANSICIONES[self.estado]:
            raise TransicionInvalidaError(
                f"Transición no permitida para la operación {self.tipo.value} de "
                f"{self.mac_objetivo}: {self.estado.value} → {destino.value}.")
        return dataclasses.replace(self, estado=destino, **cambios)

    def solicitar(self) -> "OperacionAislamiento":
        """PENDING → REQUESTED (la solicitud se entrega al motor)."""
        return self._pasar_a(EstadoOperacion.REQUESTED)

    def confirmar(self, fecha: datetime, id_aislamiento: str | None = None) -> "OperacionAislamiento":
        """REQUESTED → CONFIRMED (el motor verificó el resultado)."""
        return self._pasar_a(EstadoOperacion.CONFIRMED, fecha_resolucion=fecha,
                             id_aislamiento=id_aislamiento or self.id_aislamiento)

    def fallar(self, motivo: MotivoFallo, fecha: datetime,
               detalle: str | None = None) -> "OperacionAislamiento":
        """PENDING/REQUESTED → FAILED (efecto de red conocido)."""
        permitidos = (MOTIVOS_SIN_ENVIO if self.estado is EstadoOperacion.PENDING
                      else MOTIVOS_FALLO_CONOCIDO)
        if motivo not in permitidos and not self.terminal:
            raise TransicionInvalidaError(
                f"El motivo {motivo.value} no es válido para FAILED desde {self.estado.value}.")
        return self._pasar_a(EstadoOperacion.FAILED, fecha_resolucion=fecha,
                             motivo_fallo=motivo, detalle=_recortar(detalle))

    def marcar_incierta(self, motivo: MotivoFallo, fecha: datetime,
                        detalle: str | None = None) -> "OperacionAislamiento":
        """REQUESTED → UNCERTAIN (efecto de red desconocido; requiere recuperación)."""
        if motivo not in MOTIVOS_INCIERTOS and not self.terminal:
            raise TransicionInvalidaError(f"El motivo {motivo.value} no es válido para UNCERTAIN.")
        return self._pasar_a(EstadoOperacion.UNCERTAIN, fecha_resolucion=fecha,
                             motivo_fallo=motivo, detalle=_recortar(detalle))

    def recuperada_por(self, id_operacion: str) -> "OperacionAislamiento":
        """Enlaza la operación CONFIRMED que resolvió la incertidumbre."""
        if not self.resultado_incierto:
            raise TransicionInvalidaError("Solo una operación con resultado incierto se recupera.")
        return dataclasses.replace(self, id_recuperacion=id_operacion)

    # --- Persistencia -----------------------------------------------------------

    def a_dict(self) -> dict:
        if self.estado not in ESTADOS_PERSISTIBLES:
            raise TransicionInvalidaError("Una operación PENDING no se persiste.")
        return {
            "idOperacion": self.id_operacion,
            "macObjetivo": self.mac_objetivo,
            "tipo": self.tipo.value,
            "estado": self.estado.value,
            "fechaSolicitud": self.fecha_solicitud.isoformat(timespec="seconds"),
            "fechaResolucion": (self.fecha_resolucion.isoformat(timespec="seconds")
                                if self.fecha_resolucion else None),
            "motivoFallo": self.motivo_fallo.value if self.motivo_fallo else None,
            "detalle": self.detalle,
            "idAislamiento": self.id_aislamiento,
            "solicitadoPor": self.solicitado_por,
            "idRecuperacion": self.id_recuperacion,
        }

    @classmethod
    def desde_dict(cls, datos: dict) -> "OperacionAislamiento":
        estado = EstadoOperacion(datos["estado"])
        if estado not in ESTADOS_PERSISTIBLES:
            raise ValueError(f"Estado de operación no persistible: {estado.value}")
        motivo = datos.get("motivoFallo")
        resolucion = datos.get("fechaResolucion")
        operacion = cls(
            id_operacion=datos["idOperacion"],
            mac_objetivo=normalizar_mac(datos["macObjetivo"]),
            tipo=TipoOperacion(datos["tipo"]),
            estado=estado,
            fecha_solicitud=datetime.fromisoformat(datos["fechaSolicitud"]),
            fecha_resolucion=datetime.fromisoformat(resolucion) if resolucion else None,
            motivo_fallo=MotivoFallo(motivo) if motivo else None,
            detalle=_recortar(datos.get("detalle")),
            id_aislamiento=datos.get("idAislamiento"),
            solicitado_por=datos["solicitadoPor"],
            id_recuperacion=datos.get("idRecuperacion"),
        )
        # Coherencia mínima: FAILED/UNCERTAIN tienen motivo; los demás no.
        if (operacion.estado in _ESTADOS_CON_MOTIVO) != (operacion.motivo_fallo is not None):
            raise ValueError("Motivo de fallo incoherente con el estado de la operación.")
        if operacion.id_recuperacion is not None and not operacion.resultado_incierto:
            raise ValueError("idRecuperacion en una operación sin resultado incierto.")
        return operacion
