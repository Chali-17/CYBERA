"""ResumenController: pantalla Resumen (Mockup 02).

Indicadores (datos reales, sin inventar):
- Detectados: dispositivos en el inventario temporal del monitoreo.
- Confiables: registros de la lista blanca.
- Desconocidos: los que muestra la pantalla Dispositivos (detectado − autorizado − aislado).
- Aislados: contenciones registradas.

Actividad reciente: últimos eventos de la bitácora, del más reciente al más antiguo.

Se actualiza al mostrarse, tras cada ciclo de monitoreo, al terminar una
operación de aislamiento/desbloqueo y, mientras está visible, cada pocos segundos
(para recoger autorizaciones o cambios hechos en otras pantallas).
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QObject, QTimer

from app.models.evento_bitacora import EventoBitacora, ResultadoEvento, TipoEvento
from app.services.bitacora_service import BitacoraService
from app.services.isolation_service import IsolationService
from app.services.monitoring_service import MonitoringService
from app.services.whitelist_service import WhitelistService
from presentation.views.resumen_view import FilaActividad, Indicadores

_log = logging.getLogger(__name__)

INTERVALO_REFRESCO_MS = 4000
MAXIMO_EVENTOS = 25


class ResumenController(QObject):
    def __init__(self, vista, monitoreo: MonitoringService, lista_blanca: WhitelistService,
                 aislamiento: IsolationService, bitacora: BitacoraService,
                 controlador_monitoreo=None, ejecutor=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vista = vista
        self._monitoreo = monitoreo
        self._lista_blanca = lista_blanca
        self._aislamiento = aislamiento
        self._bitacora = bitacora
        self._activo = True
        self._firma_actividad: tuple | None = None
        vista.mostrada.connect(self.recargar)
        if controlador_monitoreo is not None:
            controlador_monitoreo.resultadoCiclo.connect(lambda _r: self._refrescar_si_visible())
            controlador_monitoreo.indicadorCambiado.connect(self._al_cambiar_indicador)
        if ejecutor is not None:
            ejecutor.terminada.connect(lambda *_: self._refrescar_si_visible())
            ejecutor.fallida.connect(lambda *_: self._refrescar_si_visible())

        self._temporizador = QTimer(self)
        self._temporizador.setInterval(INTERVALO_REFRESCO_MS)
        self._temporizador.timeout.connect(self._refrescar_si_visible)
        self._temporizador.start()

    # --- Carga -------------------------------------------------------------------
    def recargar(self) -> None:
        self._firma_actividad = None
        self._cargar()

    def _refrescar_si_visible(self) -> None:
        if self._vista.isVisible():
            self._cargar()

    def _al_cambiar_indicador(self, estado) -> None:
        self._activo = getattr(estado, "value", estado) != "INACTIVO"
        self._refrescar_si_visible()

    def _cargar(self) -> None:
        self._vista.mostrar_indicadores(self._indicadores())
        try:
            eventos = self._bitacora.historial()[:MAXIMO_EVENTOS]
        except Exception as error:  # noqa: BLE001 - p. ej. bitacora.json dañado
            self._firma_actividad = None
            self._vista.mostrar_mensaje(f"No se pudo leer la actividad reciente: {error}",
                                        error=True)
            return
        autorizados = self._autorizados()
        firma = (tuple(e.id for e in eventos), frozenset(autorizados))
        if firma == self._firma_actividad:
            return          # Nada cambió: no se redibuja (evita parpadeos).
        self._firma_actividad = firma
        hoy = date.today()
        self._vista.mostrar_actividad([_fila(e, autorizados, hoy) for e in eventos])

    def _indicadores(self) -> Indicadores:
        autorizados = self._autorizados()
        detectados = _seguro(self._monitoreo.cantidad_detectados, 0)
        desconocidos = len(_seguro(self._monitoreo.reclasificar, []))
        aislados = len(_seguro(self._aislamiento.macs_aisladas, set()))
        nota = "en el segmento monitoreado" if self._activo else "monitoreo inactivo"
        return Indicadores(detectados, len(autorizados), desconocidos, aislados, nota)

    def _autorizados(self) -> dict:
        return _seguro(self._lista_blanca.autorizados, {})


def _seguro(consulta, por_defecto):
    try:
        return consulta()
    except Exception:  # noqa: BLE001 - un archivo dañado no debe romper el Resumen
        _log.warning("Resumen: no se pudo consultar %s", getattr(consulta, "__name__", consulta),
                     exc_info=True)
        return por_defecto


# --- Formato de cada evento ------------------------------------------------------

def _fila(evento: EventoBitacora, autorizados: dict, hoy: date) -> FilaActividad:
    titulo, insignia, tono = _textos(evento, autorizados)
    momento = evento.fecha_hora
    hora = f"{momento:%H:%M:%S}" if momento.date() == hoy else f"{momento:%d/%m %H:%M}"
    return FilaActividad(hora=hora, titulo=titulo, detalle=_detalle(evento, autorizados),
                         insignia=insignia, tono=tono, ayuda=evento.descripcion or "")


def _textos(evento: EventoBitacora, autorizados: dict) -> tuple[str, str, str]:
    fallo = evento.resultado is ResultadoEvento.FALLO
    tipo = evento.tipo
    if tipo is TipoEvento.CONEXION:
        if evento.mac_dispositivo in autorizados:
            return "Dispositivo detectado", "Confiable", "verde"
        return "Nuevo dispositivo detectado", "Desconocido", "naranja"
    if tipo is TipoEvento.DESCONEXION:
        return "Dispositivo desconectado", "Finalizado", "gris"
    if tipo is TipoEvento.AUTORIZACION_DISPOSITIVO:
        if fallo:
            return "Autorización fallida", "Fallido", "ambar"
        return "Dispositivo autorizado", "Confiable", "verde"
    if tipo is TipoEvento.BLOQUEO:
        if fallo:
            return "Aislamiento fallido", "Fallido", "ambar"
        return "Aislamiento aplicado", "Aislado", "rojo"
    if tipo is TipoEvento.DESBLOQUEO:
        if fallo:
            return "Desbloqueo fallido", "Fallido", "ambar"
        return "Dispositivo desbloqueado", "Desbloqueado", "azul"
    return "Evento registrado", "Registrado", "gris"


def _detalle(evento: EventoBitacora, autorizados: dict) -> str:
    mac = evento.mac_dispositivo
    partes = [evento.ip_dispositivo or mac or "Dispositivo no identificado"]
    registro = autorizados.get(mac) if mac else None
    nombre = (registro.alias if registro is not None else None) or evento.nombre_dispositivo
    if nombre and nombre not in partes:
        partes.append(nombre)
    return "  ·  ".join(partes)
