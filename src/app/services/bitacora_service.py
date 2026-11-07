"""BitacoraService: registro, consulta y depuración del historial de eventos (módulo Bitácora).

- **Registro**: ``registrar`` crea el evento (identificador único, fecha y hora,
  tipo, datos del dispositivo, descripción y resultado) y lo persiste. Los fallos
  de escritura se registran en el log y NO se propagan: la bitácora es un historial,
  nunca debe provocar fallos en el monitoreo ni en las operaciones de aislamiento.
- **Consulta**: ``historial`` devuelve los eventos filtrados, ordenados del más
  reciente al más antiguo. Una fecha inicial posterior a la final no produce resultados.
- **Depuración**: ``depurar`` elimina el historial persistido (CU-10).

Este servicio depende de ``IBitacoraRepository`` (capa de infraestructura); la vista
no accede a la persistencia.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from app.models.evento_bitacora import EventoBitacora, ResultadoEvento, TipoEvento, nuevo_id
from infrastructure.interfaces import IBitacoraRepository

_log = logging.getLogger(__name__)


class BitacoraService:
    def __init__(self, repositorio: IBitacoraRepository,
                 reloj: Callable[[], datetime] = datetime.now) -> None:
        self._repo = repositorio
        self._reloj = reloj

    # --- Registro ------------------------------------------------------------------

    def registrar(self, tipo: TipoEvento, mac_dispositivo: str | None = None,
                 ip_dispositivo: str | None = None, nombre_dispositivo: str | None = None,
                 resultado: ResultadoEvento | None = None, descripcion: str | None = None,
                 actor: str | None = None) -> EventoBitacora:
        """Registra un evento y lo persiste. Los errores de escritura se comunican
        por log y no se propagan (la bitácora no debe romper el monitoreo)."""
        evento = EventoBitacora(
            id=nuevo_id(), tipo=tipo, fecha_hora=self._ahora(), mac_dispositivo=mac_dispositivo,
            ip_dispositivo=ip_dispositivo, nombre_dispositivo=nombre_dispositivo,
            descripcion=descripcion, resultado=resultado, actor=actor)
        try:
            return self._repo.agregar(evento)
        except Exception as error:  # noqa: BLE001 - p. ej. JSON dañado o sin permisos
            _log.warning("No se pudo registrar el evento de bitácora (%s): %s", tipo.value, error)
            return evento

    def registrar_conexion(self, mac_dispositivo: str | None, ip_dispositivo: str | None = None,
                           nombre_dispositivo: str | None = None,
                           actor: str | None = None) -> EventoBitacora:
        """Dispositivo detectado en la red (CONEXION)."""
        return self.registrar(TipoEvento.CONEXION, mac_dispositivo, ip_dispositivo, nombre_dispositivo,
                              None, self._descripcion_conexion(mac_dispositivo, ip_dispositivo), actor)

    def registrar_desconexion(self, mac_dispositivo: str | None, ip_dispositivo: str | None = None,
                              nombre_dispositivo: str | None = None,
                              actor: str | None = None) -> EventoBitacora:
        """Dispositivo que dejó de observarse en el inventario temporal (DESCONEXION)."""
        return self.registrar(TipoEvento.DESCONEXION, mac_dispositivo, ip_dispositivo, nombre_dispositivo,
                              None, f"Dispositivo {mac_dispositivo or 'desconocido'} que dejó de "
                                   "ser detectado en la red.", actor)

    def registrar_bloqueo(self, mac_dispositivo: str, actor: str | None = None,
                         resultado: ResultadoEvento = ResultadoEvento.EXITOSO,
                         descripcion: str | None = None) -> EventoBitacora:
        """Resultado de una operación de aislamiento (BLOQUEO)."""
        return self.registrar(TipoEvento.BLOQUEO, mac_dispositivo, None, None, resultado,
                              descripcion or f"Aislamiento del dispositivo {mac_dispositivo} "
                                            "confirmado por el motor de red.", actor)

    def registrar_desbloqueo(self, mac_dispositivo: str, actor: str | None = None,
                            resultado: ResultadoEvento = ResultadoEvento.EXITOSO,
                            descripcion: str | None = None) -> EventoBitacora:
        """Resultado de una operación de desbloqueo (DESBLOQUEO)."""
        return self.registrar(TipoEvento.DESBLOQUEO, mac_dispositivo, None, None, resultado,
                              descripcion or f"Desbloqueo del dispositivo {mac_dispositivo} "
                                            "confirmado por el motor de red.", actor)

    def registrar_autorizacion(self, mac_dispositivo: str, alias: str | None = None,
                               actor: str | None = None,
                               resultado: ResultadoEvento = ResultadoEvento.EXITOSO) -> EventoBitacora:
        """Dispositivo autorizado en la lista blanca (AUTORIZACION_DISPOSITIVO)."""
        return self.registrar(TipoEvento.AUTORIZACION_DISPOSITIVO, mac_dispositivo, None, alias,
                              resultado, f"Dispositivo {mac_dispositivo} autorizado en la lista blanca."
                                        + (f" (alias «{alias}»)." if alias else "."), actor)

    @staticmethod
    def _descripcion_conexion(mac_dispositivo: str | None, ip_dispositivo: str | None) -> str:
        destino = f" (IP {ip_dispositivo})" if ip_dispositivo else ""
        return f"Dispositivo {mac_dispositivo or 'desconocido'} detectado en la red local{destino}."

    # --- Consulta -------------------------------------------------------------------

    def historial(self, tipo: TipoEvento | None = None, desde: datetime | None = None,
                  hasta: datetime | None = None, mac: str | None = None,
                  tipos: Sequence[TipoEvento] | None = None) -> list[EventoBitacora]:
        """Devuelve los eventos que cumplen el filtro, del más reciente al más antiguo.

        ``tipo``: ``None`` = todos los tipos. ``desde``/``hasta``: límites inclusivos.
        Si ``desde`` es posterior a ``hasta`` no hay resultados.
        ``mac``: filtra por dirección MAC cuando se indica.
        ``tipos``: lista de tipos; cuando se indica, se usa en lugar de ``tipo`` (p. ej.
        para agrupar aislamientos y desbloqueos como «Aislamientos»).
        """
        if desde is not None and hasta is not None and desde > hasta:
            return []
        seleccion = tipos if tipos is not None else ([tipo] if tipo is not None else None)
        eventos = self._repo.eventos()
        resultado = [e for e in eventos
                     if ((seleccion is None or e.tipo in seleccion)
                         and (desde is None or desde <= e.fecha_hora)
                         and (hasta is None or e.fecha_hora <= hasta)
                         and (mac is None or e.mac_dispositivo == mac))]
        return sorted(resultado, key=lambda e: e.fecha_hora, reverse=True)

    # --- Depuración -----------------------------------------------------------------

    def depurar(self) -> int:
        """Elimina el historial persistido (CU-10). Devuelve la cantidad de eventos eliminados."""
        eventos = self._repo.eventos()
        self._repo.vaciar()
        return len(eventos)

    # --- Auxiliares ------------------------------------------------------------------

    def _ahora(self) -> datetime:
        return self._reloj().replace(microsecond=0)
