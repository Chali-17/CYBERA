"""Ubicación de los archivos locales de CYBERA."""

from __future__ import annotations

import os
from pathlib import Path

VARIABLE_DIRECTORIO = "CYBERA_DATOS"

ARCHIVO_CONFIGURACION = "configuracion.json"
ARCHIVO_LISTA_BLANCA = "lista_blanca.json"
ARCHIVO_AISLAMIENTOS = "aislamientos.json"


def directorio_datos() -> Path:
    """%APPDATA%\\CYBERA, o la carpeta indicada en la variable CYBERA_DATOS."""
    personalizado = os.environ.get(VARIABLE_DIRECTORIO)
    if personalizado:
        return Path(personalizado)
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "CYBERA"
