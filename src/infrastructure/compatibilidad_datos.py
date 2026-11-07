"""Separación entre la carpeta de datos actual y la de versiones anteriores (L5).

Hallazgo (inspección de solo lectura de PG2_DESARROLLO/ControlAislamiento, v3,
v4, v5, v6 y v7): todas las versiones anteriores escriben en la carpeta FIJA
``%APPDATA%\\ControlAislamiento`` (``almacen.directorio_datos``), sin variable
para cambiarla, con un formato propio y sin conocer el bloqueo ``cybera.lock``.
CYBERA actual usa ``%APPDATA%\\CYBERA`` (o ``CYBERA_DATOS``).

Por tanto, las versiones antiguas solo podrían escribir sobre los mismos
archivos si CYBERA se apuntara a esa carpeta. Esta comprobación lo impide:
CYBERA no arranca (ni crea su bloqueo) sobre una carpeta que se llame
``ControlAislamiento`` o que contenga archivos que solo escriben las versiones
anteriores. No se modifica ni se borra nada de esas carpetas.
"""

from __future__ import annotations

import json
from pathlib import Path

CARPETA_HEREDADA = "ControlAislamiento"
# Archivos que solo crean las versiones anteriores (almacen.ARCHIVOS).
ARCHIVOS_HEREDADOS = ("dispositivos.json", "alertas.json", "notificaciones.json",
                      "bitacora.jsonl")
# CYBERA actual también usa «notificaciones.json» (remitente de los avisos por
# correo). Ese nombre solo se considera heredado si NO tiene el formato actual.
ARCHIVO_COMPARTIDO = "notificaciones.json"


def _es_notificaciones_actual(ruta: Path) -> bool:
    """True si ``ruta`` es el notificaciones.json de CYBERA ({"version", "remitente"})."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(datos, dict) and "remitente" in datos and "version" in datos


def _es_heredado(directorio: Path, nombre: str) -> bool:
    ruta = directorio / nombre
    if not ruta.exists():
        return False
    return not (nombre == ARCHIVO_COMPARTIDO and _es_notificaciones_actual(ruta))


def problema_carpeta_datos(directorio: Path) -> str | None:
    """Motivo por el que CYBERA no debe usar ``directorio``, o None si es seguro."""
    directorio = Path(directorio)
    if directorio.name.casefold() == CARPETA_HEREDADA.casefold():
        return (f"La carpeta de datos «{directorio}» es la de versiones anteriores de la "
                "aplicación (ControlAislamiento), que no respetan el bloqueo de instancia "
                "de CYBERA. Use otra carpeta (variable CYBERA_DATOS).")
    try:
        presentes = [n for n in ARCHIVOS_HEREDADOS if _es_heredado(directorio, n)]
    except OSError as error:
        return f"No se pudo comprobar la carpeta de datos «{directorio}»: {error}"
    if presentes:
        return (f"La carpeta de datos «{directorio}» contiene archivos de una versión "
                f"anterior ({', '.join(presentes)}). Una versión anterior podría escribir en "
                "ella sin respetar el bloqueo de CYBERA. Use otra carpeta (variable "
                "CYBERA_DATOS).")
    return None
