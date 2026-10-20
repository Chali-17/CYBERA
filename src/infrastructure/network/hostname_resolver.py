"""Resolución inversa de nombre de host.

En Windows, ``gethostbyaddr`` consulta DNS inverso y, según la configuración
del sistema, LLMNR/NetBIOS. Muchos teléfonos, televisores y equipos IoT no
publican su nombre por estos medios: en ese caso se devuelve None.
"""

from __future__ import annotations

import socket

from infrastructure.interfaces import IHostnameResolver


class SocketHostnameResolver(IHostnameResolver):
    def resolver(self, ip: str) -> str | None:
        try:
            nombre = socket.gethostbyaddr(ip)[0].strip()
        except (OSError, UnicodeError):
            return None
        if not nombre or nombre == ip:
            return None
        return nombre
