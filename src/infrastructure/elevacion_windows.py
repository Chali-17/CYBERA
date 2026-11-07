"""Elevación a administrador para el motor de aislamiento real (Windows).

El motor de aislamiento por envenenamiento ARP
(``infrastructure.network.arp_spoofing.ArpSpoofingIsolationEngine``) construye y
transmite las tramas suplantadas a través de Scapy/Npcap. En Windows, enviar tramas
RAW requiere que el proceso tenga privilegios de administrador; sin ellos el motor se
declara «no disponible» y la opción «Aislar» de la aplicación no puede bloquear al
dispositivo intruso.

Este módulo centraliza el arranque con la elevación necesaria:

- ``es_administrador()``: ¿el proceso corre con privilegios de administrador?
- ``solicitar_elevacion()``: si no los hay (en Windows), pide la elevación con
  ``ShellExecuteW`` usando el verbo «runas» (control de cuentas de usuario) y
  devuelve ``True`` si la aplicación debe continuar ya elevada (o si ya lo está).
  En cualquier otro caso devuelve ``False`` sin efectos.

No modifica la lógica de aislamiento: el motor sigue siendo quien decide y confirma
el envío de las tramas (contrato ``INetworkIsolation``). La elevación es un requisito
de capacidad del SO para que esas tramas puedan transmitirse.

El resto de módulos de detección (``windows_arp``, ``windows_interfaces``) no requieren
privilegios; solo el motor de contención (ARP) los exige.
"""

from __future__ import annotations

import ctypes
import sys

_VERBO_ELEVACION = "runas"
_SW_SHOWNORMAL = 1


def es_administrador() -> bool:
    """True si el proceso actual tiene privilegios de administrador (Windows)."""
    if sys.platform != "win32":
        # Fuera de Windows no aplica el concepto (y los tests corren en Linux).
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - sin shell32 o API no disponible
        return False


def _argumentos() -> str:
    """Argumentos de línea de comandos de esta instancia, entre comillas."""
    return " ".join(f'"{arg}"' for arg in sys.argv[1:])


def _ejecutar_shell_ejecutable(archivo: str, parametros: str) -> bool:
    """Lanza ``archivo`` con el verbo «runas» vía ShellExecuteW. True si se lanzó."""
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.ShellExecuteW.restype = ctypes.c_long
        shell32.ShellExecuteW.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_void_p, ctypes.c_int,
        ]
        resultado = shell32.ShellExecuteW(
            None, _VERBO_ELEVACION, archivo, parametros, None, _SW_SHOWNORMAL)
        return bool(resultado) and resultado > 32
    except Exception:  # noqa: BLE001 - sin shell32 o en otro SO
        return False


def solicitar_elevacion() -> bool:
    """Devuelve True si la aplicación debe continuar (ya elevada o con admin).

    Si el proceso NO es administrador en Windows, intenta reanudarse con el verbo
    «runas» (elevación). Devuelve True si la elevación fue aceptada (la instancia
    elevada tomará el control) o si ya lo está; False si no procede.
    """
    if sys.platform != "win32":
        return False
    if es_administrador():
        return True
    return _ejecutar_shell_ejecutable(sys.executable, _argumentos())
