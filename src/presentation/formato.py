"""Textos de presentación de un PerfilDispositivo (sin inventar datos)."""

from __future__ import annotations

from app.models.dispositivo import PerfilDispositivo

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
