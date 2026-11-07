"""BitacoraController: coordina la vista Bitácora con el BitacoraService.

Recarga el historial según los filtros de la vista, informa errores de lectura
sin bloquear la aplicación y ejecuta la depuración manual (CU-10) tras la
confirmación explícita del usuario. Mientras la pantalla está visible, revisa
periódicamente si hay eventos nuevos (los registra el monitoreo en segundo plano).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from app.models.evento_bitacora import TipoEvento
from app.services.bitacora_service import BitacoraService

INTERVALO_REFRESCO_MS = 4000


class BitacoraController(QObject):
    recargarSolicitado = Signal()
    tipoCambiado = Signal(object)
    rangoCambiado = Signal(object, object)
    depurarSolicitado = Signal()

    def __init__(self, vista, bitacora: BitacoraService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vista = vista
        self._bitacora = bitacora
        self._enviando_depuracion = False
        self._firma: tuple | None = None          # Evita redibujar si nada cambió.
        vista.mostrada.connect(self.recargar)
        vista.recargarSolicitado.connect(self.recargar)
        vista.tipoCambiado.connect(self._al_cambiar_tipo)
        vista.rangoCambiado.connect(self._al_cambiar_rango)
        vista.depurarSolicitado.connect(self._solicitar_depuracion)

        self._temporizador = QTimer(self)
        self._temporizador.setInterval(INTERVALO_REFRESCO_MS)
        self._temporizador.timeout.connect(self._refrescar_si_visible)
        self._temporizador.start()

    # --- Consulta ---------------------------------------------------------------
    def recargar(self) -> None:
        """Carga el historial con los filtros actuales de la vista."""
        self._firma = None
        self._vista.mostrar_cargando()
        self._cargar()

    def _cargar(self) -> None:
        tipo = self._vista.tipo()
        desde, hasta = self._vista.rango()
        try:
            eventos = self._bitacora.historial(tipo=tipo, desde=desde, hasta=hasta)
        except Exception as error:  # noqa: BLE001 - p. ej. bitacora.json dañado
            self._firma = None
            self._vista.mostrar_mensaje(f"No se pudo leer la bitácora de eventos: {error}", error=True)
            return
        firma = (tipo, desde, hasta, len(eventos), eventos[0].id if eventos else None)
        if firma == self._firma:
            return
        self._firma = firma
        self._vista.mostrar_eventos(eventos)

    def _refrescar_si_visible(self) -> None:
        if self._vista.isVisible() and not self._enviando_depuracion:
            self._cargar()

    def _al_cambiar_tipo(self, tipo: TipoEvento | None) -> None:
        self.recargar()

    def _al_cambiar_rango(self, desde, hasta) -> None:
        self.recargar()

    # --- Depuración -------------------------------------------------------------
    def _solicitar_depuracion(self) -> None:
        if self._enviando_depuracion:
            return          # Una misma acción no se ejecuta dos veces.
        self._enviando_depuracion = True
        try:
            if not self._bitacora.historial():
                self._vista.informar("Vaciar historial", "El historial de eventos ya está vacío.")
                return
            if not self._vista.confirmar_depuracion():
                return      # El usuario canceló: no se modifica ningún registro.
            eliminados = self._bitacora.depurar()
        except Exception as error:  # noqa: BLE001 - p. ej. fallo de lectura/escritura
            self._vista.mostrar_mensaje(f"No se pudo vaciar la bitácora: {error}", error=True)
            return
        finally:
            self._enviando_depuracion = False
        self._vista.informar("Historial vaciado",
                             f"Se eliminaron {eliminados} eventos del historial.")
        self.recargar()
