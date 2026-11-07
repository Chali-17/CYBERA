"""Componentes visuales comunes: página con encabezado, panel e indicador."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont, QPalette, QTextCharFormat
from PySide6.QtWidgets import QApplication, QCalendarWidget, QFrame, QTableView, QHBoxLayout, QLabel, QVBoxLayout, QWidget

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


def fuente_negrita() -> QFont:
    """Fuente base de la aplicación, en negrita.

    Parte de ``QApplication.font()`` (tamaño válido, origen único) en lugar de la
    fuente de un ``QTableWidgetItem`` recién creado, cuyo ``pointSize()`` es -1 y
    provoca el aviso ``QFont::setPointSize: Point size <= 0 (-1)``.
    """
    fuente = QApplication.font()
    fuente.setBold(True)
    return fuente


def estilizar_calendario(calendario: QCalendarWidget) -> QCalendarWidget:
    """Calendario claro y uniforme (independiente del tema oscuro de Windows)."""
    from presentation.estilos import AZUL, TEXTO, TEXTO_SUAVE
    calendario.setGridVisible(False)
    calendario.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
    # Paleta propia (no hoja de estilos): así la selección y los días de otros meses
    # se dibujan bien aunque Windows use tema oscuro o el calendario no tenga el foco.
    paleta = QPalette()
    for grupo in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        paleta.setColor(grupo, QPalette.ColorRole.Base, QColor("white"))
        paleta.setColor(grupo, QPalette.ColorRole.AlternateBase, QColor("white"))
        paleta.setColor(grupo, QPalette.ColorRole.Window, QColor("white"))
        paleta.setColor(grupo, QPalette.ColorRole.Text, QColor(TEXTO))
        paleta.setColor(grupo, QPalette.ColorRole.WindowText, QColor(TEXTO))
        paleta.setColor(grupo, QPalette.ColorRole.ButtonText, QColor(TEXTO))
        paleta.setColor(grupo, QPalette.ColorRole.Highlight, QColor(AZUL))
        paleta.setColor(grupo, QPalette.ColorRole.HighlightedText, QColor("white"))
    paleta.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#CBD5E1"))
    calendario.setPalette(paleta)
    vista = calendario.findChild(QTableView)
    if vista is not None:
        vista.setPalette(paleta)
    dias = QTextCharFormat()
    dias.setForeground(QColor(TEXTO))
    for dia in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
        calendario.setWeekdayTextFormat(dia, dias)
    cabecera = QTextCharFormat()
    cabecera.setForeground(QColor(TEXTO_SUAVE))
    calendario.setHeaderTextFormat(cabecera)
    calendario.selectionChanged.connect(lambda: resaltar_fechas(calendario))
    resaltar_fechas(calendario)
    return calendario


def resaltar_fechas(calendario: QCalendarWidget, desde: QDate | None = None,
                    hasta: QDate | None = None) -> None:
    """Pinta la fecha seleccionada (y, si se indica, el periodo desde–hasta).

    El estilo de Windows 11 no dibuja la selección cuando el calendario no tiene
    el foco, así que se marca con formatos de texto propios.
    """
    from presentation.estilos import AZUL
    calendario.setDateTextFormat(QDate(), QTextCharFormat())      # Limpia marcas anteriores.
    if desde is not None and hasta is not None and desde <= hasta and desde.daysTo(hasta) <= 366:
        tramo = QTextCharFormat()
        tramo.setBackground(QColor("#DBEAFE"))
        dia = desde
        while dia <= hasta:
            calendario.setDateTextFormat(dia, tramo)
            dia = dia.addDays(1)
    elegido = QTextCharFormat()
    elegido.setBackground(QColor(AZUL))
    elegido.setForeground(QColor("white"))
    elegido.setFontWeight(QFont.Weight.Bold)
    calendario.setDateTextFormat(calendario.selectedDate(), elegido)


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
    """Encabezado (título, subtítulo, indicador) y contenido de la pantalla."""

    def __init__(self, titulo: str, subtitulo: str, parent: QWidget | None = None) -> None:
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

    def set_indicador(self, estado: EstadoIndicador) -> None:
        self.indicador.set_estado(estado)
