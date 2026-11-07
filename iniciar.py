"""Inicia CYBERA:  python iniciar.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from infrastructure.elevacion_windows import es_administrador, solicitar_elevacion  # noqa: E402


def _iniciar() -> int:
    # El motor de aislamiento real (envenenamiento ARP) necesita privilegios de
    # administrador en Windows para enviar las tramas de contención. Si la aplicación
    # se ejecuta sin ellos, se reanuda ya elevada (ShellExecute «runas») antes de
    # arrancar la interfaz; la instancia elevada continúa el arranque.
    if sys.platform == "win32" and not es_administrador():
        if not solicitar_elevacion():
            # Sin capacidad de elevación: no se inicia la aplicación.
            return 1
        # La elevación fue aceptada: esta instancia cede el turno a la reanudación
        # elevada y termina sin arrancar la interfaz.
        return 0
    from app.main import main  # noqa: E402
    return main()


if __name__ == "__main__":
    sys.exit(_iniciar())
