"""Diagnóstico de red para el motor de aislamiento (solo lectura).

    python diagnostico_aislamiento.py            # diagnóstico sin capturar tráfico
    python diagnostico_aislamiento.py -o 6       # añade 6 s de observación PASIVA

No envía, modifica ni descarta tráfico, ni suplanta direcciones. No habilita el
aislamiento: solo informa qué capacidades reales existen en este equipo.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from infrastructure.network.diagnostico_motor import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
