"""Fabricante a partir del OUI de la MAC (RF01).

Fuente: archivo ``manuf`` de Wireshark, generado a partir de los registros
públicos del IEEE (MA-L de 24 bits, MA-M de 28 bits y MA-S de 36 bits).
El archivo se incluye en ``recursos/oui/manuf``; no se consulta Internet.
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.models.mac import normalizar_mac
from infrastructure.interfaces import IOuiResolver


class WiresharkManufResolver(IOuiResolver):
    def __init__(self, ruta: Path) -> None:
        self._ruta = Path(ruta)
        self._tablas: dict[int, dict[int, str]] | None = None
        self._lock = threading.Lock()

    @property
    def disponible(self) -> bool:
        return self._ruta.is_file()

    def _cargar(self) -> dict[int, dict[int, str]]:
        with self._lock:
            if self._tablas is not None:
                return self._tablas
            tablas: dict[int, dict[int, str]] = {}
            if self._ruta.is_file():
                with self._ruta.open("r", encoding="utf-8", errors="replace") as archivo:
                    for linea in archivo:
                        if not linea.strip() or linea.startswith("#"):
                            continue
                        columnas = [c.strip() for c in linea.rstrip("\n").split("\t")]
                        columnas = [c for c in columnas if c]
                        if len(columnas) < 2:
                            continue
                        prefijo, _, bits_texto = columnas[0].partition("/")
                        hexadecimal = prefijo.replace(":", "").replace("-", "")
                        try:
                            valor = int(hexadecimal, 16)
                        except ValueError:
                            continue
                        bits = int(bits_texto) if bits_texto else len(hexadecimal) * 4
                        if not 0 < bits <= 48:
                            continue
                        valor = (valor << (48 - len(hexadecimal) * 4)) >> (48 - bits)
                        nombre = columnas[2] if len(columnas) >= 3 else columnas[1]
                        tablas.setdefault(bits, {})[valor] = nombre
            self._tablas = tablas
            return tablas

    def fabricante(self, mac: str) -> str | None:
        valor = int(normalizar_mac(mac).replace(":", ""), 16)
        tablas = self._cargar()
        for bits in sorted(tablas, reverse=True):  # Prefijo más largo primero.
            nombre = tablas[bits].get(valor >> (48 - bits))
            if nombre:
                return nombre
        return None
