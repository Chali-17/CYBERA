"""Vista «Ayuda»: consulta de los manuales en PDF de la carpeta MANUEALES.

Muestra cada manual dentro de la aplicación y permite abrirlo con el visor
predeterminado de Windows o guardar una copia donde el usuario elija.
Los archivos originales no se mueven, renombran ni modifican.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QWidget)

from presentation.estilos import BORDE, FONDO
from presentation.widgets import Panel, PaginaBase


class AyudaView(PaginaBase):
    def __init__(self, manuales: dict[str, Path], parent: QWidget | None = None) -> None:
        super().__init__("Ayuda", "Manuales de usuario y de instalación", parent)
        self._manuales = manuales
        self._actual: Path | None = None

        panel = Panel("Manuales")
        diseno = panel.diseno

        # --- Selección del manual y acciones -----------------------------------
        fila = QHBoxLayout()
        fila.setSpacing(20)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self.botones_manual: dict[str, QPushButton] = {}
        for titulo in manuales:
            boton = QPushButton(titulo)
            boton.setObjectName("opcion")
            boton.setCheckable(True)
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.clicked.connect(lambda _=False, t=titulo: self.mostrar(t))
            self._grupo.addButton(boton)
            self.botones_manual[titulo] = boton
            fila.addWidget(boton)
        fila.addStretch(1)
        self.boton_abrir = QPushButton("Abrir")
        self.boton_abrir.setObjectName("botonAzul")
        self.boton_abrir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_abrir.setToolTip("Abrir con el visor de PDF predeterminado")
        self.boton_abrir.clicked.connect(self._abrir)
        self.boton_descargar = QPushButton("Descargar")
        self.boton_descargar.setObjectName("botonNeutro")
        self.boton_descargar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_descargar.setToolTip("Guardar una copia del manual")
        self.boton_descargar.clicked.connect(self._descargar)
        fila.addWidget(self.boton_abrir)
        fila.addWidget(self.boton_descargar)
        diseno.addLayout(fila)

        # --- Visor integrado ------------------------------------------------------
        self.documento = QPdfDocument(self)
        self.visor = QPdfView()
        self.visor.setDocument(self.documento)
        self.visor.setPageMode(QPdfView.PageMode.MultiPage)
        self.visor.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        # Fondo claro alrededor de las páginas, acorde con la paleta de la aplicación.
        paleta = self.visor.palette()
        paleta.setColor(QPalette.ColorRole.Dark, QColor(FONDO))
        self.visor.setPalette(paleta)
        self.visor.setStyleSheet(f"QPdfView {{ border: 1px solid {BORDE}; border-radius: 8px; }}")
        diseno.addWidget(self.visor, 1)

        self.mensaje = QLabel()
        self.mensaje.setObjectName("mensajeTabla")
        self.mensaje.setProperty("error", True)
        self.mensaje.hide()
        diseno.addWidget(self.mensaje)

        self.contenido.addWidget(panel, 1)
        if manuales:
            self.mostrar(next(iter(manuales)))

    def mostrar(self, titulo: str) -> None:
        ruta = self._manuales[titulo]
        self.botones_manual[titulo].setChecked(True)
        self.documento.close()
        self._actual = None
        if ruta.is_file() and self.documento.load(str(ruta)) == QPdfDocument.Error.None_:
            self._actual = ruta
            self.mensaje.hide()
        else:
            self.mensaje.setText(f"No se pudo cargar el manual: {ruta}")
            self.mensaje.show()
        self.boton_abrir.setEnabled(self._actual is not None)
        self.boton_descargar.setEnabled(self._actual is not None)

    def _abrir(self) -> None:
        if self._actual is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._actual)))

    def _descargar(self) -> None:
        if self._actual is None:
            return
        sugerido = str(Path.home() / "Downloads" / self._actual.name)
        destino, _ = QFileDialog.getSaveFileName(self, "Guardar manual", sugerido,
                                                 "Documento PDF (*.pdf)")
        if not destino:
            return
        try:
            shutil.copyfile(self._actual, destino)
        except OSError as error:
            QMessageBox.warning(self, "Ayuda", f"No se pudo guardar el manual:\n{error}")
            return
        QMessageBox.information(self, "Ayuda", f"Manual guardado en:\n{destino}")
