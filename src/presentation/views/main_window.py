"""Ventana principal: barra lateral de navegación y área de contenido."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from app.controllers.monitoring_controller import EstadoIndicador
from presentation.estilos import ANCHO_BARRA_LATERAL
from presentation.widgets import PaginaBase

# Orden del Mockup. Las opciones sin página se muestran de forma estática.
# «Alertas» se retiró del alcance funcional (sus funciones son redundantes con Dispositivos).
OPCIONES = ["Resumen", "Dispositivos", "Lista blanca", "Aislamiento",
            "Bitácora", "Reportes", "Configuración", "Ayuda"]
_PENDIENTE = "Módulo pendiente de desarrollo."


class MainWindow(QMainWindow):
    def __init__(self, paginas: dict[str, PaginaBase], inicial: str = "Dispositivos") -> None:
        super().__init__()
        self.setWindowTitle("CYBERA — Control y aislamiento")
        self.setMinimumSize(1100, 700)
        self._paginas = paginas

        raiz = QWidget()
        raiz.setObjectName("raiz")
        diseno = QHBoxLayout(raiz)
        diseno.setContentsMargins(0, 0, 0, 0)
        diseno.setSpacing(0)

        barra = QFrame()
        barra.setObjectName("barraLateral")
        barra.setFixedWidth(ANCHO_BARRA_LATERAL)
        lateral = QVBoxLayout(barra)
        lateral.setContentsMargins(20, 30, 20, 24)
        lateral.setSpacing(8)
        marca = QLabel("CYBERA")
        marca.setObjectName("marca")
        marca.setContentsMargins(14, 0, 0, 0)
        subtitulo = QLabel("Control y aislamiento")
        subtitulo.setObjectName("marcaSub")
        subtitulo.setContentsMargins(14, 0, 0, 0)
        lateral.addWidget(marca)
        lateral.addWidget(subtitulo)
        lateral.addSpacing(30)

        self._pila = QStackedWidget()
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self.botones: dict[str, QPushButton] = {}
        for opcion in OPCIONES:
            if opcion in paginas:
                boton = QPushButton(opcion)
                boton.setObjectName("nav")
                boton.setCheckable(True)
                boton.setCursor(Qt.CursorShape.PointingHandCursor)
                self._pila.addWidget(paginas[opcion])
                boton.clicked.connect(lambda _=False, o=opcion: self.ir_a(o))
                self._grupo.addButton(boton)
                self.botones[opcion] = boton
                lateral.addWidget(boton)
            else:
                etiqueta = QLabel(opcion)
                etiqueta.setObjectName("nav")
                etiqueta.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                etiqueta.setToolTip(_PENDIENTE)
                lateral.addWidget(etiqueta)
        lateral.addStretch(1)

        diseno.addWidget(barra)
        diseno.addWidget(self._pila, 1)
        self.setCentralWidget(raiz)
        self.ir_a(inicial)

    def ir_a(self, opcion: str) -> None:
        self._pila.setCurrentWidget(self._paginas[opcion])
        self.botones[opcion].setChecked(True)

    def set_indicador(self, estado: EstadoIndicador) -> None:
        for pagina in self._paginas.values():
            pagina.set_indicador(estado)
