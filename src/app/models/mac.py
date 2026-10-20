"""Reglas de dominio sobre direcciones MAC (RI-01, RI-03 del Modelo de datos)."""

from __future__ import annotations

import re

_SEPARADORES = re.compile(r"[\s:\-.]")
_HEX = set("0123456789ABCDEF")


def normalizar_mac(valor: str) -> str:
    """Devuelve la MAC en formato canónico ``AA:BB:CC:DD:EE:FF``.

    Acepta separadores ``:``, ``-``, ``.`` o ninguno. Lanza ``ValueError`` si el
    formato no es válido (RI-03).
    """
    if not isinstance(valor, str):
        raise ValueError("La dirección MAC debe ser texto.")
    hexadecimal = _SEPARADORES.sub("", valor).upper()
    if len(hexadecimal) != 12 or not set(hexadecimal) <= _HEX:
        raise ValueError(f"Formato de dirección MAC inválido: {valor!r}")
    return ":".join(hexadecimal[i:i + 2] for i in range(0, 12, 2))


def es_mac_valida(valor: str) -> bool:
    try:
        normalizar_mac(valor)
    except ValueError:
        return False
    return True


def _primer_octeto(mac: str) -> int:
    return int(normalizar_mac(mac)[:2], 16)


def es_multicast(mac: str) -> bool:
    """Bit I/G activo: multicast o difusión (no identifica a un equipo)."""
    return bool(_primer_octeto(mac) & 0x01)


def es_administrada_localmente(mac: str) -> bool:
    """Bit U/L activo: MAC asignada por software (p. ej. «MAC aleatoria» o VM).

    Estas direcciones no pertenecen a un bloque registrado ante el IEEE, por lo
    que no permiten inferir el fabricante.
    """
    return bool(_primer_octeto(mac) & 0x02)


def es_mac_de_dispositivo(mac: str) -> bool:
    """True si la MAC puede identificar a un equipo concreto (unicast, no nula)."""
    if not es_mac_valida(mac):
        return False
    canonica = normalizar_mac(mac)
    return canonica != "00:00:00:00:00:00" and not es_multicast(canonica)
