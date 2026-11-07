"""Vista «Lista blanca» (Mockup 04): directorio de dispositivos de confianza."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from app.models.dispositivo_confiable import DispositivoConfiable
from presentation.views.edit_whitelist_dialog import DatosEdicion, EditarListaBlancaDialog
from presentation.widgets import PaginaBase, fuente_negrita

COLUMNAS = ["Alias", "MAC", "Fecha", "Estado", "Acción"]
# Proporciones de ancho aproximadas al Mockup 04.
_PROPORCIONES = [0.27, 0.22, 0.18, 0.18, 0.15]
_ALTO_FILA = 64
SIN_ALIAS = "Sin alias"
FECHA_NO_DISPONIBLE = "No disponible"


class _TablaListaBlanca(QTableWidget):
    def __init__(self) -> None:
        super().__init__(0, len(COLUMNAS))
        self.setObjectName("tablaDispositivos")   # Reutiliza el estilo de tabla.
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


class WhitelistView(PaginaBase):
    agregarSolicitado = Signal()
    editarSolicitado = Signal(str)       # MAC
    mostrada = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Lista blanca", "Directorio de dispositivos de confianza", parent)
        panel = self._crear_panel()
        self.contenido.addWidget(panel, 1)
        self.mostrar_mensaje("Cargando dispositivos autorizados…")

    def _crear_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        diseno = QVBoxLayout(panel)
        diseno.setContentsMargins(34, 30, 34, 30)
        diseno.setSpacing(18)

        encabezado = QHBoxLayout()
        titulo = QLabel("Dispositivos autorizados")
        titulo.setObjectName("tituloPanel")
        encabezado.addWidget(titulo)
        encabezado.addStretch(1)
        self.boton_agregar = QPushButton("Agregar")
        self.boton_agregar.setObjectName("botonAzul")
        self.boton_agregar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_agregar.setToolTip("Ir a Dispositivos para autorizar un equipo detectado.")
        self.boton_agregar.clicked.connect(self.agregarSolicitado.emit)
        encabezado.addWidget(self.boton_agregar)
        diseno.addLayout(encabezado)

        self._pila = QStackedWidget()
        self._tabla = _TablaListaBlanca()
        self._mensaje = QLabel()
        self._mensaje.setObjectName("mensajeTabla")
        self._mensaje.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mensaje.setWordWrap(True)
        self._pila.addWidget(self._tabla)
        self._pila.addWidget(self._mensaje)
        diseno.addWidget(self._pila, 1)
        return panel

    # --- Eventos -----------------------------------------------------------
    def showEvent(self, evento) -> None:  # noqa: N802 - API de Qt
        super().showEvent(evento)
        self.mostrada.emit()

    @property
    def filas(self) -> int:
        return self._tabla.rowCount() if self._pila.currentWidget() is self._tabla else 0

    # --- API usada por WhitelistController ---------------------------------
    def mostrar_mensaje(self, texto: str, error: bool = False) -> None:
        self._tabla.setRowCount(0)
        self._mensaje.setText(texto)
        self._mensaje.setProperty("error", "true" if error else "false")
        self._mensaje.style().unpolish(self._mensaje)
        self._mensaje.style().polish(self._mensaje)
        self._pila.setCurrentWidget(self._mensaje)

    def mostrar_dispositivos(self, registros: list[DispositivoConfiable]) -> None:
        if not registros:
            self.mostrar_mensaje("No hay dispositivos autorizados. Use «Agregar» para "
                                 "autorizar un equipo desde Dispositivos.")
            return
        self._tabla.setRowCount(len(registros))
        for fila, registro in enumerate(registros):
            self._llenar_fila(fila, registro)
        self._pila.setCurrentWidget(self._tabla)

    def solicitar_edicion(self, datos: DatosEdicion) -> tuple[str | None, str | None]:
        dialogo = EditarListaBlancaDialog(datos, self)
        dialogo.exec()
        return dialogo.accion, dialogo.alias()

    def confirmar_eliminacion(self, alias: str, mac: str) -> bool:
        respuesta = QMessageBox.warning(
            self, "Eliminar de lista blanca",
            f"Se eliminará la autorización del dispositivo:\n\n"
            f"    Alias: {alias}\n    MAC:   {mac}\n\n"
            "El equipo dejará de estar autorizado y, si se vuelve a detectar y no está "
            "aislado, reaparecerá en Dispositivos como pendiente de revisión. Esto NO "
            "aísla ni bloquea su conexión. ¿Desea continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return respuesta == QMessageBox.StandardButton.Yes

    def confirmar_aislamiento(self, alias: str, mac: str, ip: str | None) -> bool:
        respuesta = QMessageBox.warning(
            self, "Confirmar aislamiento",
            f"Se intentará aislar de la red el dispositivo:\n\n"
            f"    Alias: {alias}\n    MAC:   {mac}\n    IP:    {ip or 'No disponible'}\n\n"
            "El dispositivo perdería la conectividad según el mecanismo de aislamiento "
            "implementado. ¿Desea continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return respuesta == QMessageBox.StandardButton.Yes

    def informar(self, titulo: str, texto: str) -> None:
        QMessageBox.information(self, titulo, texto)

    def advertir(self, titulo: str, texto: str) -> None:
        QMessageBox.warning(self, titulo, texto)

    # --- Interno -----------------------------------------------------------
    def _item(self, texto: str) -> QTableWidgetItem:
        item = QTableWidgetItem(texto)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _llenar_fila(self, fila: int, registro: DispositivoConfiable) -> None:
        alias = QTableWidgetItem(registro.alias or SIN_ALIAS)
        alias.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        alias.setFont(fuente_negrita())
        self._tabla.setItem(fila, 0, alias)
        self._tabla.setItem(fila, 1, self._item(registro.mac))
        fecha = (registro.fecha_autorizacion.strftime("%d/%m/%Y")
                 if registro.fecha_autorizacion else FECHA_NO_DISPONIBLE)
        self._tabla.setItem(fila, 2, self._item(fecha))
        self._tabla.setItem(fila, 3, QTableWidgetItem())
        self._tabla.setCellWidget(fila, 3, self._celda_estado())
        self._tabla.setItem(fila, 4, QTableWidgetItem())
        self._tabla.setCellWidget(fila, 4, self._celda_accion(registro.mac))

    def _celda_estado(self) -> QWidget:
        celda = QWidget()
        celda.setObjectName("celdaAccion")
        celda.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        diseno = QHBoxLayout(celda)
        diseno.setContentsMargins(14, 0, 0, 0)
        pastilla = QLabel("Confiable")
        pastilla.setObjectName("pastillaConfiable")
        diseno.addWidget(pastilla)
        diseno.addStretch(1)
        return celda

    def _celda_accion(self, mac: str) -> QWidget:
        celda = QWidget()
        celda.setObjectName("celdaAccion")
        celda.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        diseno = QHBoxLayout(celda)
        diseno.setContentsMargins(14, 0, 0, 0)
        boton = QPushButton("Editar")
        boton.setObjectName("botonEditar")
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        boton.clicked.connect(lambda _=False, m=mac: self.editarSolicitado.emit(m))
        diseno.addWidget(boton)
        diseno.addStretch(1)
        return celda
