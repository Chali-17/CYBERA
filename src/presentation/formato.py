"""Textos de presentación de un PerfilDispositivo (sin inventar datos)."""

from __future__ import annotations

from app.models.dispositivo import PerfilDispositivo
from app.models.operacion_aislamiento import EstadoOperacion, MotivoFallo, TipoOperacion

DESCONOCIDO = "Desconocido"
NO_DISPONIBLE = "No disponible"
FABRICANTE_MAC_LOCAL = "No disponible (MAC aleatoria)"
AYUDA_MAC_LOCAL = ("La dirección MAC está administrada localmente: es la «dirección aleatoria» "
                   "que usan teléfonos y Windows para proteger la privacidad, o la de una máquina "
                   "virtual. No pertenece a un fabricante registrado ante el IEEE.")


def texto_nombre(perfil: PerfilDispositivo) -> str:
    """Alias de la lista blanca → hostname → «Desconocido»."""
    base = perfil.alias or perfil.hostname or DESCONOCIDO
    if perfil.es_este_equipo:
        return f"{base} (este equipo)"
    if perfil.es_puerta_enlace:
        return f"{base} (puerta de enlace)"
    return base


def texto_fabricante(perfil: PerfilDispositivo) -> str:
    if perfil.fabricante:
        return perfil.fabricante
    return FABRICANTE_MAC_LOCAL if perfil.mac_local else NO_DISPONIBLE


def ayuda_fabricante(perfil: PerfilDispositivo) -> str:
    if perfil.fabricante:
        return f"{perfil.fabricante}\nFuente: registro OUI del IEEE (archivo manuf de Wireshark)."
    if perfil.mac_local:
        return AYUDA_MAC_LOCAL
    return "El prefijo de la MAC no figura en el registro OUI incluido."


def ayuda_nombre(perfil: PerfilDispositivo) -> str:
    lineas = [
        f"Alias (lista blanca): {perfil.alias or 'sin alias'}",
        f"Nombre de host: {perfil.hostname or NO_DISPONIBLE}",
    ]
    if perfil.fuente is not None:
        lineas.append(f"Detección: {perfil.fuente.value}")
    lineas.append(f"Primera detección en esta sesión: {perfil.primera_deteccion:%H:%M:%S}")
    lineas.append(f"Última detección: {perfil.ultima_deteccion:%H:%M:%S}")
    return "\n".join(lineas)


SIN_REGISTRO = "Sin aislamiento registrado"
REGISTRADO_SIN_VERIFICAR = "Registrado, estado sin verificar"
_MOTIVOS_RESULTADO_DESCONOCIDO = frozenset({
    MotivoFallo.ERROR_MOTOR, MotivoFallo.SIN_CONFIRMACION, MotivoFallo.INTERRUMPIDA,
    MotivoFallo.AUTORIZADA, MotivoFallo.AUTORIZACION_NO_VERIFICABLE})


def texto_situacion_aislamiento(situacion) -> str:
    """Estado de aislamiento SIN afirmar hechos de red no verificados (H4).

    ``situacion`` es una ``SituacionAislamiento`` de IsolationService. Se
    distingue el registro administrativo (aislamientos.json) de la verificación
    del motor en ESTA ejecución. Ningún texto afirma conectividad: el motor solo
    informa si aplica contención.
    """
    if situacion.en_curso is TipoOperacion.AISLAR:
        return "Aislamiento solicitado, sin confirmar"
    if situacion.en_curso is TipoOperacion.DESBLOQUEAR:
        return "Desbloqueo solicitado, sin confirmar"

    if getattr(situacion, "requiere_recuperacion", False):
        incierta = situacion.operacion_incierta
        que = ("aislamiento" if incierta is None or incierta.tipo is TipoOperacion.AISLAR
               else "desbloqueo")
        texto = f"Requiere recuperación: resultado incierto del último {que}"
        if situacion.verificacion is not None:
            texto += (f" (el motor informó {situacion.verificacion.estado.value} a las "
                      f"{situacion.verificacion.fecha:%H:%M:%S})")
        return texto

    ultima = situacion.ultima_operacion
    fallida = ultima is not None and ultima.estado is EstadoOperacion.FAILED
    verificacion = situacion.verificacion
    if verificacion is not None:
        hora = f"{verificacion.fecha:%H:%M:%S}"
        estado = verificacion.estado.value
        if estado == "CONTENCION_APLICADA":
            texto = f"Contención aplicada según el motor (verificado a las {hora})"
            if not situacion.registrado:
                texto += "; sin aislamiento registrado"
            elif fallida and ultima.tipo is TipoOperacion.DESBLOQUEAR:
                texto += "; el último desbloqueo falló"
            return texto
        if estado == "SIN_CONTENCION":
            if situacion.registrado:
                return (f"Registrado como aislado, pero el motor no aplica contención "
                        f"(verificado a las {hora})")
            return f"Sin contención según el motor (verificado a las {hora})"
        return "Estado sin verificar: el motor no pudo determinarlo"

    if situacion.registrado:
        return REGISTRADO_SIN_VERIFICAR
    if fallida and ultima.motivo_fallo in _MOTIVOS_RESULTADO_DESCONOCIDO:
        que = "aislamiento" if ultima.tipo is TipoOperacion.AISLAR else "desbloqueo"
        return f"Estado sin verificar: el último {que} no se confirmó"
    return SIN_REGISTRO


def insignia_aislamiento(situacion) -> tuple[str, str]:
    """(texto, tono) de la insignia de la pantalla Aislamiento (Mockup 06).

    El Mockup 06 muestra «Aislado» en rojo. Ese texto solo se usa cuando el motor
    VERIFICÓ en esta ejecución que aplica contención. Los demás estados usan
    textos y tonos distintos para que nunca se confundan con un aislamiento
    comprobado. El detalle completo va en la ayuda (texto_situacion_aislamiento).
    """
    if situacion.en_curso is TipoOperacion.AISLAR:
        return "Aislando…", "gris"
    if situacion.en_curso is TipoOperacion.DESBLOQUEAR:
        return "Desbloqueando…", "gris"
    if getattr(situacion, "requiere_recuperacion", False):
        return "Requiere recuperación", "ambar"
    verificacion = situacion.verificacion
    if verificacion is not None and situacion.registrado:
        estado = verificacion.estado.value
        if estado == "CONTENCION_APLICADA":
            return "Aislado", "rojo"
        if estado == "SIN_CONTENCION":
            return "No coincide", "ambar"
    return "Sin verificar", "ambar"
