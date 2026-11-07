"""Vista «Bitácora» (Mockup 07): historial cronológico de eventos de seguridad.

- Tabla con fecha y hora, evento, dispositivo, IP y resultado (más reciente primero).
- «Filtrar por tipo» y «Fecha desde / hasta» (combinables; no modifican los registros).
- «Vaciar historial» con confirmación explícita.
- Estados de carga, historial vacío y errores sin bloquear la aplicación.

No incluye funciones de exportación: eso pertenece al módulo de Reportes.
"""

from __future__ import annotations

from datetime import date, datetime, time

from PySide6.QtCore import QDate, QPoint, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCalendarWidget, QComboBox, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app.models.evento_bitacora import (ETIQUETA_TIPO, EventoBitacora, TipoEvento, etiqueta_resultado,
                                        etiqueta_tipo)
from presentation import formato
from presentation.widgets import (Panel, PaginaBase, estilizar_calendario, fuente_negrita, repulir,
                                  resaltar_fechas)

COLUMNAS = ["Fecha y hora", "Evento", "Dispositivo", "IP", "Resultado"]
_PROPORCIONES = [0.2, 0.18, 0.25, 0.17, 0.2]
_ALTO_FILA = 62
_ANCHO_FILTRO = 290
TEXTO_RANGO_VACIO = "Fecha desde / hasta"

SIN_EVENTOS = ("El historial de eventos está vacío. No hay registros de conexión, desconexión, "
               "aislamiento ni autorización.")
SIN_COINCIDENCIAS = "No hay eventos que coincidan con los filtros seleccionados."


class _TablaEventos(QTableWidget):
    def __init__(self) -> None:
        super().__init__(0, len(COLUMNAS))
        self.setObjectName("tablaDispositivos")   # Reutiliza el estilo de tabla existente.
        self.setHorizontalHeaderLabels(COLUMNAS)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(_ALTO_FILA)
        self.setShowGrid(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWordWrap(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        cabecera = self.horizontalHeader()
        cabecera.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cabecera.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        cabecera.setHighlightSections(False)
        cabecera.setFixedHeight(52)

    def resizeEvent(self, evento) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(evento)
        ancho = self.viewport().width()
        for columna, proporcion in enumerate(_PROPORCIONES):
            self.setColumnWidth(columna, int(ancho * proporcion))


class _PopupRango(QFrame):
    """Ventana emergente con dos calendarios (desde / hasta) para elegir el periodo."""

    aplicado = Signal(object, object)     # date | None, date | None

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("popupRango")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        diseno = QVBoxLayout(self)
        diseno.setContentsMargins(18, 16, 18, 16)
        diseno.setSpacing(12)

        calendarios = QHBoxLayout()
        calendarios.setSpacing(18)
        self.calendario_desde = self._calendario()
        self.calendario_hasta = self._calendario()
        for titulo, calendario in (("Desde", self.calendario_desde), ("Hasta", self.calendario_hasta)):
            columna = QVBoxLayout()
            columna.setSpacing(6)
            etiqueta = QLabel(titulo)
            etiqueta.setObjectName("etiquetaCampo")
            columna.addWidget(etiqueta)
            columna.addWidget(calendario)
            calendarios.addLayout(columna)
        diseno.addLayout(calendarios)
        self.calendario_desde.selectionChanged.connect(self._resaltar_periodo)
        self.calendario_hasta.selectionChanged.connect(self._resaltar_periodo)

        self._aviso = QLabel()
        self._aviso.setObjectName("aviso")
        self._aviso.setProperty("exito", "false")
        diseno.addWidget(self._aviso)

        botones = QHBoxLayout()
        botones.addStretch(1)
        quitar = QPushButton("Quitar filtro")
        quitar.setObjectName("botonNeutro")
        quitar.setCursor(Qt.CursorShape.PointingHandCursor)
        quitar.clicked.connect(self._quitar)
        aplicar = QPushButton("Aplicar")
        aplicar.setObjectName("botonAzul")
        aplicar.setCursor(Qt.CursorShape.PointingHandCursor)
        aplicar.clicked.connect(self._aplicar)
        botones.addWidget(quitar)
        botones.addWidget(aplicar)
        diseno.addLayout(botones)

    @staticmethod
    def _calendario() -> QCalendarWidget:
        calendario = estilizar_calendario(QCalendarWidget())
        calendario.setMinimumSize(300, 230)
        calendario.setMaximumDate(QDate.currentDate())
        return calendario

    def _resaltar_periodo(self) -> None:
        desde = self.calendario_desde.selectedDate()
        hasta = self.calendario_hasta.selectedDate()
        for calendario in (self.calendario_desde, self.calendario_hasta):
            resaltar_fechas(calendario, desde, hasta)

    def abrir(self, ancla: QWidget, desde: date | None, hasta: date | None) -> None:
        hoy = QDate.currentDate()
        self.calendario_desde.setSelectedDate(QDate(desde) if desde else hoy.addDays(-7))
        self.calendario_hasta.setSelectedDate(QDate(hasta) if hasta else hoy)
        self._aviso.setText("")
        self.adjustSize()
        self.move(ancla.mapToGlobal(QPoint(0, ancla.height() + 6)))
        self.show()

    def _aplicar(self) -> None:
        desde = self.calendario_desde.selectedDate().toPython()
        hasta = self.calendario_hasta.selectedDate().toPython()
        if desde > hasta:
            self._aviso.setText("La fecha «Desde» no puede ser posterior a la fecha «Hasta».")
            return
        self.hide()
        self.aplicado.emit(desde, hasta)

    def _quitar(self) -> None:
        self.hide()
        self.aplicado.emit(None, None)


class BitacoraView(PaginaBase):
    recargarSolicitado = Signal()
    tipoCambiado = Signal(object)
    rangoCambiado = Signal(object, object)
    depurarSolicitado = Signal()
    mostrada = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Bitácora", "Historial cronológico de eventos",
                         parent)
        self._desde: date | None = None
        self._hasta: date | None = None

        panel = Panel("Historial de seguridad")
        panel.diseno.addSpacing(6)

        # --- Filtros y acciones (Mockup 07) -------------------------------------
        filtros = QHBoxLayout()
        filtros.setSpacing(26)

        self.combo_tipo = QComboBox()
        self.combo_tipo.setObjectName("campo")
        self.combo_tipo.setFixedWidth(_ANCHO_FILTRO)
        self.combo_tipo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_tipo.setToolTip("Filtrar por tipo de evento")
        self.combo_tipo.addItem("Todos")
        self._tipos: list[TipoEvento | None] = [None]     # Índice 0 = Todos.
        for tipo in TipoEvento:
            self._tipos.append(tipo)
            self.combo_tipo.addItem(ETIQUETA_TIPO[tipo])
        self.combo_tipo.currentIndexChanged.connect(self._al_cambiar_tipo)
        filtros.addWidget(self.combo_tipo)

        self.boton_rango = QPushButton(TEXTO_RANGO_VACIO)
        self.boton_rango.setObjectName("campoBoton")
        self.boton_rango.setFixedWidth(_ANCHO_FILTRO)
        self.boton_rango.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_rango.setToolTip("Filtrar por periodo")
        self.boton_rango.setProperty("activo", "false")
        self._popup_rango = _PopupRango(self)
        self._popup_rango.aplicado.connect(self.establecer_rango)
        self.boton_rango.clicked.connect(
            lambda: self._popup_rango.abrir(self.boton_rango, self._desde, self._hasta))
        filtros.addWidget(self.boton_rango)
        filtros.addStretch(1)

        self.boton_vaciar = QPushButton("Vaciar\nhistorial")
        self.boton_vaciar.setObjectName("botonVaciar")
        self.boton_vaciar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_vaciar.setToolTip("Elimina todos los eventos registrados (pide confirmación).")
        self.boton_vaciar.clicked.connect(lambda: self.depurarSolicitado.emit())
        filtros.addWidget(self.boton_vaciar)
        panel.diseno.addLayout(filtros)

        # --- Tabla / mensajes ---------------------------------------------------
        self._pila = QStackedWidget()
        self._tabla = _TablaEventos()
        self._mensaje = QLabel()
        self._mensaje.setObjectName("mensajeTabla")
        self._mensaje.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mensaje.setWordWrap(True)
        self._pila.addWidget(self._tabla)
        self._pila.addWidget(self._mensaje)
        panel.diseno.addWidget(self._pila, 1)

        self._conteo = QLabel()
        self._conteo.setObjectName("ayuda")
        panel.diseno.addWidget(self._conteo)

        self.contenido.addWidget(panel, 1)
        self.mostrar_mensaje("Cargando historial de eventos…")

    # --- Eventos -------------------------------------------------------------
    def showEvent(self, evento) -> None:  # noqa: N802 - API de Qt
        super().showEvent(evento)
        self.mostrada.emit()

    def _al_cambiar_tipo(self, _indice: int) -> None:
        self.tipoCambiado.emit(self.tipo())

    def establecer_rango(self, desde: date | None, hasta: date | None) -> None:
        """Fija (o quita, con ``None``) el periodo consultado y notifica al controlador."""
        self._desde, self._hasta = desde, hasta
        if desde is None or hasta is None:
            self._desde = self._hasta = None
            self.boton_rango.setText(TEXTO_RANGO_VACIO)
            self.boton_rango.setProperty("activo", "false")
        else:
            self.boton_rango.setText(f"{desde:%d/%m/%Y}  –  {hasta:%d/%m/%Y}")
            self.boton_rango.setProperty("activo", "true")
        repulir(self.boton_rango)
        self.rangoCambiado.emit(*self.rango())

    # --- API usada por BitacoraController --------------------------------------
    def tipo(self) -> TipoEvento | None:
        indice = self.combo_tipo.currentIndex()
        return self._tipos[indice] if indice > 0 else None

    def rango(self) -> tuple[datetime | None, datetime | None]:
        """Límites inclusivos: desde las 00:00:00 hasta las 23:59:59 del último día."""
        if self._desde is None or self._hasta is None:
            return (None, None)
        return (datetime.combine(self._desde, time.min),
                datetime.combine(self._hasta, time(23, 59, 59)))

    def hay_filtros(self) -> bool:
        return self.tipo() is not None or self._desde is not None

    def mostrar_mensaje(self, texto: str, error: bool = False) -> None:
        self._tabla.setRowCount(0)
        self._conteo.setText("")
        self._mensaje.setText(texto)
        self._mensaje.setProperty("error", "true" if error else "false")
        repulir(self._mensaje)
        self._pila.setCurrentWidget(self._mensaje)

    def mostrar_cargando(self) -> None:
        if self._pila.currentWidget() is not self._tabla:
            self.mostrar_mensaje("Cargando historial de eventos…")

    def mostrar_eventos(self, eventos: list[EventoBitacora]) -> None:
        if not eventos:
            self.mostrar_mensaje(SIN_COINCIDENCIAS if self.hay_filtros() else SIN_EVENTOS)
            return
        self._tabla.setRowCount(len(eventos))
        for fila, evento in enumerate(eventos):
            self._llenar_fila(fila, evento)
        self._pila.setCurrentWidget(self._tabla)
        self._conteo.setText("1 evento" if len(eventos) == 1 else f"{len(eventos)} eventos")

    def confirmar_depuracion(self) -> bool:
        respuesta = QMessageBox.warning(
            self, "Vaciar historial",
            "Se eliminarán TODOS los eventos registrados en la bitácora, sin importar los "
            "filtros aplicados.\n\nEsta acción no se puede deshacer. Si necesita conservarlos, "
            "genere antes un reporte desde «Reportes».\n\n¿Desea vaciar el historial?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return respuesta == QMessageBox.StandardButton.Yes

    def informar(self, titulo: str, texto: str) -> None:
        QMessageBox.information(self, titulo, texto)

    # --- Interno -------------------------------------------------------------
    def _item(self, texto: str, negrita: bool = False, ayuda: str | None = None) -> QTableWidgetItem:
        item = QTableWidgetItem(str(texto))
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if negrita:
            item.setFont(fuente_negrita())
        if ayuda:
            item.setToolTip(ayuda)
        return item

    def _llenar_fila(self, fila: int, evento: EventoBitacora) -> None:
        ayuda = evento.descripcion
        dispositivo = evento.mac_dispositivo or evento.nombre_dispositivo or formato.NO_DISPONIBLE
        if evento.nombre_dispositivo and evento.mac_dispositivo:
            ayuda = f"{evento.nombre_dispositivo}\n{ayuda or ''}".strip()
        valores = [
            evento.fecha_hora.strftime("%d/%m/%Y %H:%M:%S"),
            etiqueta_tipo(evento.tipo),
            dispositivo,
            evento.ip_dispositivo or formato.NO_DISPONIBLE,
            etiqueta_resultado(evento.resultado),
        ]
        for columna, valor in enumerate(valores):
            self._tabla.setItem(fila, columna, self._item(valor, negrita=columna == 1, ayuda=ayuda))
