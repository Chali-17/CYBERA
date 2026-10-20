"""Inicia CYBERA:  python iniciar.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
