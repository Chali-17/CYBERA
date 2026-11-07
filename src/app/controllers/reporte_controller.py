"""ReporteController: coordina la vista Reportes con el ReporteService.

Consulta los eventos con los filtros de la vista, pide al usuario dónde guardar,
genera el archivo (CSV o PDF), informa el resultado y maneja errores sin bloquear
la interfaz. Una exportación en curso no se ejecuta dos veces.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.services.reporte_service import FORMATO_PDF, ReporteService


class ReporteController(QObject):
    generarSolicitado = Signal()

    def __init__(self, vista, reporte: ReporteService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vista = vista
        self._reporte = reporte
        self._enviando = False
        vista.generarSolicitado.connect(self._generar)

    def _generar(self) -> None:
        if self._enviando:
            return
        self._enviando = True
        self._vista.set_generando(True)
        try:
            ruta, cantidad = self._exportar()
        except Exception as error:  # noqa: BLE001 - lectura o generación de reporte
            self._vista.mostrar_mensaje(f"No se pudo generar el reporte: {error}", error=True)
            return
        finally:
            self._enviando = False
            self._vista.set_generando(False)
        if ruta is not None:
            self._vista.mostrar_mensaje(f"Reporte guardado en {ruta}")
            self._vista.informar_generado(ruta, cantidad)

    def _exportar(self):
        """Devuelve (ruta, cantidad) o (None, 0) si no se generó nada."""
        tipos = self._vista.tipos()
        desde, hasta = self._vista.rango()
        if desde > hasta:
            self._vista.mostrar_mensaje("La fecha inicial no puede ser posterior a la fecha final.",
                                        error=True)
            return None, 0
        eventos = self._reporte.historial(tipos=tipos, desde=desde, hasta=hasta)
        if not eventos:
            self._vista.mostrar_mensaje(
                "No hay registros para los filtros seleccionados: no se generó el reporte.", error=True)
            return None, 0
        formato = self._vista.formato()
        destino = self._vista.elegir_destino(self._reporte.ruta_reporte(formato), formato)
        if destino is None:
            self._vista.mostrar_mensaje("Exportación cancelada.")
            return None, 0
        self._vista.mostrar_cargando()
        if formato == FORMATO_PDF:
            ruta = self._reporte.guardar_pdf(eventos, desde=desde, hasta=hasta, tipo=tipos, ruta=destino)
        else:
            ruta = self._reporte.guardar_csv(eventos, ruta=destino)
        return ruta, len(eventos)
