"""Vista «Reportes» (Mockup 08): exportación del historial de la bitácora a PDF o CSV.

- Periodo (fecha desde / fecha hasta), por defecto del día 1 del mes actual a hoy.
- Tipo de eventos: Todos, Conexiones, Desconexiones o Aislamientos.
- Formato de salida: PDF o CSV.
- «Generar reporte» pide dónde guardar el archivo y ejecuta la exportación.

No incluye lógica de registro ni de persistencia: solo consulta y exporta.
"""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QDateEdit, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QWidget)

from app.models.evento_bitacora import TipoEvento
from presentation.widgets import Panel, PaginaBase, estilizar_calendario, repulir

OPCION_TODOS = "todos"
OPCION_CONEXIONES = "conexiones"
OPCION_DESCONEXIONES = "desconexiones"
OPCION_AISLAMIENTOS = "aislamientos"

OPCION_TEXTO = {
    OPCION_TODOS: "Todos",
    OPCION_CONEXIONES: "Conexiones",
    OPCION_DESCONEXIONES: "Desconexiones",
    OPCION_AISLAMIENTOS: "Aislamientos",
}

OPCION_TIPOS: dict[str, list[TipoEvento] | None] = {
    OPCION_TODOS: None,
    OPCION_CONEXIONES: [TipoEvento.CONEXION],
    OPCION_DESCONEXIONES: [TipoEvento.DESCONEXION],
    OPCION_AISLAMIENTOS: [TipoEvento.BLOQUEO, TipoEvento.DESBLOQUEO],
}

FORMATO_PDF = "pdf"
FORMATO_CSV = "csv"
_FILTRO_DIALOGO = {FORMATO_PDF: "Documento PDF (*.pdf)", FORMATO_CSV: "Archivo CSV (*.csv)"}

INFO_EXPORTACION = "El archivo incluirá fecha, evento, nodo, IP, MAC y resultado."


def _etiqueta(texto: str) -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("etiquetaCampo")
    return etiqueta


def _campo_fecha(fecha: QDate) -> QDateEdit:
    campo = QDateEdit()
    campo.setObjectName("campo")
    campo.setCalendarPopup(True)
    estilizar_calendario(campo.calendarWidget())
    campo.setDisplayFormat("dd/MM/yyyy")
    campo.setMaximumDate(QDate.currentDate())
    campo.setDate(fecha)
    campo.setFixedWidth(300)
    return campo


class ReporteView(PaginaBase):
    generarSolicitado = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Reportes", "Exportación de telemetría histórica", parent)
        panel = Panel("Generar reporte")
        diseno = panel.diseno
        diseno.addSpacing(22)

        # --- Periodo -----------------------------------------------------------
        hoy = QDate.currentDate()
        diseno.addWidget(_etiqueta("Periodo"))
        self.calendario_desde = _campo_fecha(QDate(hoy.year(), hoy.month(), 1))
        self.calendario_desde.setToolTip("Fecha desde")
        self.calendario_hasta = _campo_fecha(hoy)
        self.calendario_hasta.setToolTip("Fecha hasta")
        fila_periodo = QHBoxLayout()
        fila_periodo.setSpacing(28)
        fila_periodo.addWidget(self.calendario_desde)
        fila_periodo.addWidget(self.calendario_hasta)
        fila_periodo.addStretch(1)
        diseno.addLayout(fila_periodo)
        diseno.addSpacing(26)

        # --- Tipo de eventos ----------------------------------------------------
        diseno.addWidget(_etiqueta("Tipo de eventos"))
        self._grupo_tipo = QButtonGroup(self)
        self._grupo_tipo.setExclusive(True)
        self._boton_tipo: dict[str, QPushButton] = {}
        fila_tipo = QHBoxLayout()
        fila_tipo.setSpacing(28)
        for clave, texto in OPCION_TEXTO.items():
            boton = self._opcion(texto, 182)
            self._grupo_tipo.addButton(boton)
            self._boton_tipo[clave] = boton
            fila_tipo.addWidget(boton)
        fila_tipo.addStretch(1)
        self._boton_tipo[OPCION_TODOS].setChecked(True)
        diseno.addLayout(fila_tipo)
        diseno.addSpacing(36)

        # --- Formato de salida ---------------------------------------------------
        diseno.addWidget(_etiqueta("Formato de salida"))
        grupo_formato = QButtonGroup(self)
        grupo_formato.setExclusive(True)
        self._boton_formato_pdf = self._opcion("PDF", 132)
        self._boton_formato_csv = self._opcion("CSV", 132)
        grupo_formato.addButton(self._boton_formato_pdf)
        grupo_formato.addButton(self._boton_formato_csv)
        self._boton_formato_pdf.setChecked(True)
        fila_formato = QHBoxLayout()
        fila_formato.setSpacing(20)
        fila_formato.addWidget(self._boton_formato_pdf)
        fila_formato.addWidget(self._boton_formato_csv)
        fila_formato.addStretch(1)
        diseno.addLayout(fila_formato)
        diseno.addSpacing(30)

        # --- Pie del panel: ayuda + «Generar reporte» ----------------------------
        pie = QHBoxLayout()
        self._info = QLabel(INFO_EXPORTACION)
        self._info.setObjectName("ayuda")
        pie.addWidget(self._info, 0, Qt.AlignmentFlag.AlignTop)
        pie.addStretch(1)
        self.boton_generar = QPushButton("Generar reporte")
        self.boton_generar.setObjectName("botonAzul")
        self.boton_generar.setMinimumWidth(246)
        self.boton_generar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_generar.clicked.connect(lambda: self.generarSolicitado.emit())
        pie.addWidget(self.boton_generar)
        diseno.addLayout(pie)

        self._mensaje = QLabel()
        self._mensaje.setObjectName("aviso")
        self._mensaje.setWordWrap(True)
        self._mensaje.setProperty("error", "false")
        diseno.addWidget(self._mensaje)
        diseno.addStretch(1)

        self.contenido.addWidget(panel, 1)

    def _opcion(self, texto: str, ancho: int) -> QPushButton:
        boton = QPushButton(texto)
        boton.setObjectName("opcion")
        boton.setCheckable(True)
        boton.setFixedWidth(ancho)
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        return boton

    # --- API usada por ReporteController --------------------------------------------

    def opcion_tipo(self) -> str:
        for clave, boton in self._boton_tipo.items():
            if boton.isChecked():
                return clave
        return OPCION_TODOS

    def seleccionar_tipo(self, opcion: str) -> None:
        self._boton_tipo[opcion].setChecked(True)

    def tipos(self) -> list[TipoEvento] | None:
        """Tipos de evento seleccionados para el reporte (None = todos)."""
        seleccion = OPCION_TIPOS[self.opcion_tipo()]
        return list(seleccion) if seleccion is not None else None

    def rango(self) -> tuple[datetime, datetime]:
        """Límites inclusivos: desde las 00:00:00 hasta las 23:59:59 del último día."""
        desde = self.calendario_desde.date().toPython()
        hasta = self.calendario_hasta.date().toPython()
        return (datetime.combine(desde, time.min), datetime.combine(hasta, time(23, 59, 59)))

    def formato(self) -> str:
        """Formato de salida seleccionado: ``pdf`` o ``csv``."""
        return FORMATO_PDF if self._boton_formato_pdf.isChecked() else FORMATO_CSV

    def seleccionar_formato(self, formato: str) -> None:
        (self._boton_formato_pdf if formato == FORMATO_PDF else self._boton_formato_csv).setChecked(True)

    def elegir_destino(self, sugerida: Path, formato: str) -> Path | None:
        """Pregunta dónde guardar el reporte. ``None`` si el usuario cancela."""
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar reporte", str(sugerida),
                                              _FILTRO_DIALOGO[formato])
        if not ruta:
            return None
        destino = Path(ruta)
        if destino.suffix.lower() != "." + formato:
            destino = destino.with_name(destino.name + "." + formato)
        return destino

    def set_generando(self, activo: bool) -> None:
        """Deshabilita el botón «Generar reporte» durante la exportación."""
        self.boton_generar.setEnabled(not activo)
        self.boton_generar.setText("Generando…" if activo else "Generar reporte")

    def mostrar_mensaje(self, texto: str, error: bool = False) -> None:
        self._mensaje.setText(texto)
        self._mensaje.setProperty("error", "true" if error else "false")
        self._mensaje.setProperty("exito", "false" if error else "true")
        repulir(self._mensaje)

    def mostrar_cargando(self, texto: str = "Generando reporte…") -> None:
        self.mostrar_mensaje(texto)

    def informar_generado(self, ruta: Path, cantidad: int) -> None:
        """Informa el resultado y ofrece abrir el archivo o su carpeta."""
        caja = QMessageBox(QMessageBox.Icon.Information, "Reporte generado",
                           f"Se exportaron {cantidad} eventos.\n\nArchivo:\n{ruta}", parent=self)
        abrir = caja.addButton("Abrir archivo", QMessageBox.ButtonRole.AcceptRole)
        carpeta = caja.addButton("Abrir carpeta", QMessageBox.ButtonRole.ActionRole)
        caja.addButton("Cerrar", QMessageBox.ButtonRole.RejectRole)
        caja.exec()
        if caja.clickedButton() is abrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))
        elif caja.clickedButton() is carpeta:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta.parent)))
