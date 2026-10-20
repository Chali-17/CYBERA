"""Ejecución de cmdlets de PowerShell con salida JSON.

Se usan los cmdlets del módulo NetTCPIP/NetAdapter incluidos en Windows 10/11.
Su salida JSON no depende del idioma del sistema (a diferencia de ``arp -a`` o
``ipconfig``).
"""

from __future__ import annotations

import json
import subprocess

_CREATE_NO_WINDOW = 0x08000000
_PREFIJO = ("$ErrorActionPreference = 'Stop'; "
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; ")


class PowerShellError(RuntimeError):
    pass


def ejecutar_json(script: str, timeout: float = 30.0) -> list[dict]:
    """Ejecuta ``script`` (que debe imprimir JSON) y devuelve una lista de objetos."""
    comando = ["powershell.exe", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass", "-Command", _PREFIJO + script]
    try:
        proceso = subprocess.run(comando, capture_output=True, timeout=timeout,
                                 creationflags=_CREATE_NO_WINDOW)
    except FileNotFoundError as error:
        raise PowerShellError("No se encontró powershell.exe en el sistema.") from error
    except subprocess.TimeoutExpired as error:
        raise PowerShellError("PowerShell no respondió a tiempo.") from error
    if proceso.returncode != 0:
        detalle = proceso.stderr.decode("utf-8", errors="replace").strip()
        raise PowerShellError(detalle or f"PowerShell terminó con código {proceso.returncode}.")
    salida = proceso.stdout.decode("utf-8-sig", errors="replace").strip()
    if not salida:
        return []
    try:
        datos = json.loads(salida)
    except json.JSONDecodeError as error:
        raise PowerShellError(f"Salida de PowerShell no válida: {error}") from error
    if isinstance(datos, dict):
        return [datos]
    return [d for d in datos if isinstance(d, dict)]
