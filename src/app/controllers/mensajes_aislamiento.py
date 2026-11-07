"""Títulos y textos de las confirmaciones visuales de aislamiento y desbloqueo.

Distinguen: no disponible, operación en curso, fallida (efecto conocido),
resultado incierto (requiere recuperación), sin verificar (no registrada) y
rechazo. Ningún texto afirma conectividad: el motor solo informa contención.
"""

from __future__ import annotations

from app.models.operacion_aislamiento import EstadoOperacion
from app.services.isolation_service import (AislamientoFallidoError, AislamientoNoDisponibleError,
                                            DesbloqueoFallidoError, OperacionEnCursoError,
                                            RegistroAislamientoError)

TITULO_RECUPERACION = "Resultado incierto: requiere recuperación"


def _titulo(error: Exception, que: str, fallido_tipo: type, fallido: str, rechazo: str) -> str:
    if getattr(error, "requiere_recuperacion", False):
        return TITULO_RECUPERACION
    if isinstance(error, AislamientoNoDisponibleError):
        return f"{que} no disponible"
    if isinstance(error, OperacionEnCursoError):
        return "Operación en curso"
    if isinstance(error, fallido_tipo):
        return fallido
    operacion = getattr(error, "operacion", None)
    if (isinstance(error, RegistroAislamientoError) and operacion is not None
            and operacion.estado is EstadoOperacion.REQUESTED):
        # El motor ya actuó pero el resultado no quedó registrado (H4).
        return f"{que} sin verificar"
    return rechazo


def titulo_error_aislamiento(error: Exception) -> str:
    return _titulo(error, "Aislamiento", AislamientoFallidoError, "Aislamiento fallido",
                   "No se pudo aislar")


def titulo_error_desbloqueo(error: Exception) -> str:
    return _titulo(error, "Desbloqueo", DesbloqueoFallidoError, "Desbloqueo fallido",
                   "No se pudo desbloquear")


def texto_contencion_confirmada(mac: str) -> str:
    return (f"El motor de red confirmó que aplica contención a {mac}. Es el estado que "
            "informa el motor; no es una comprobación independiente de la conectividad "
            "del dispositivo.")


def texto_contencion_retirada(mac: str, recuperacion: bool) -> str:
    base = (f"El motor de red confirmó que ya no aplica contención a {mac}. Esto no "
            "comprueba por sí solo que el dispositivo haya recuperado la conectividad.")
    if recuperacion:
        base += " La recuperación pendiente quedó resuelta."
    return base
