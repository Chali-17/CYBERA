"""Componentes visuales comunes: página con encabezado, panel e indicador."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.controllers.monitoring_controller import EstadoIndicador

_TEXTO_INDICADOR = {
    EstadoIndicador.ACTIVO: "●  MONITOREO ACTIVO",
    EstadoIndicador.INACTIVO: "●  MONITOREO INACTIVO",
    EstadoIndicador.ERROR: "●  MONITOREO CON INCIDENCIA",
}
_AYUDA_INDICADOR = {
    EstadoIndicador.ACTIVO: "El descubrimiento de dispositivos está en ejecución.",
    EstadoIndicador.INACTIVO: "No se realizan escaneos. El monitoreo se controla en Configuración.",
    EstadoIndicador.ERROR: ("El monitoreo está activado, pero no puede descubrir dispositivos. "
                            "Consulte el mensaje de la pantalla Dispositivos."),
}


def repulir(widget: QWidget) -> None:
    """Vuelve a aplicar el estilo tras cambiar una propiedad dinámica."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class IndicadorMonitoreo(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("indicador")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_estado(EstadoIndicador.INACTIVO)

    def set_estado(self, estado: EstadoIndicador) -> None:
        self.setText(_TEXTO_INDICADOR[estado])
        self.setToolTip(_AYUDA_INDICADOR[estado])
        self.setProperty("estado", estado.value)
        repulir(self)


class Panel(QFrame):
    """Panel blanco con bordes redondeados y título."""

    def __init__(self, titulo: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.diseno = QVBoxLayout(self)
        self.diseno.setContentsMargins(34, 30, 34, 30)
        self.diseno.setSpacing(18)
        self.titulo = QLabel(titulo)
        self.titulo.setObjectName("tituloPanel")
        self.diseno.addWidget(self.titulo)


class PaginaBase(QWidget):
    """Encabezado (título, subtítulo, indicador), contenido y pie de pantalla."""

    def __init__(self, titulo: str, subtitulo: str, pie: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pagina")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(40, 26, 44, 14)
        raiz.setSpacing(0)

        encabezado = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(10)
        etiqueta_titulo = QLabel(titulo)
        etiqueta_titulo.setObjectName("tituloPagina")
        etiqueta_subtitulo = QLabel(subtitulo)
        etiqueta_subtitulo.setObjectName("subtituloPagina")
        textos.addWidget(etiqueta_titulo)
        textos.addWidget(etiqueta_subtitulo)
        encabezado.addLayout(textos)
        encabezado.addStretch(1)
        self.indicador = IndicadorMonitoreo()
        encabezado.addWidget(self.indicador, 0, Qt.AlignmentFlag.AlignTop)
        raiz.addLayout(encabezado)
        raiz.addSpacing(28)

        self.contenido = QVBoxLayout()
        self.contenido.setSpacing(22)
        raiz.addLayout(self.contenido, 1)

        raiz.addSpacing(18)
        etiqueta_pie = QLabel(pie)
        etiqueta_pie.setObjectName("pie")
        raiz.addWidget(etiqueta_pie)

    def set_indicador(self, estado: EstadoIndicador) -> None:
        self.indicador.set_estado(estado)
