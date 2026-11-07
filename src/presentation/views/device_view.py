"""Vista «Dispositivos» (Mockup 03)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QWidget)

from app.models.dispositivo import PerfilDispositivo
from presentation import formato
from presentation.estilos import TEXTO
from presentation.views.review_dialog import RevisarDispositivoDialog
from presentation.widgets import Panel, PaginaBase, fuente_negrita, repulir

COLUMNAS = ["Dispositivos conectados", "IP", "MAC", "Fabricante", "Estado", "Acción"]
# Proporciones de ancho medidas en el Mockup 03.
_PROPORCIONES = [0.237, 0.154, 0.185, 0.165, 0.144, 0.115]
_ALTO_FILA = 62

AYUDA_LIMITACIONES = (
    "Se listan los equipos que respondieron a una solicitud ARP en la interfaz seleccionada,\n"
    "o que Windows confirmó recientemente como alcanzables. Puede no ser una lista completa:\n"
    "un equipo en ahorro de energía o separado por el «aislamiento de clientes» del router\n"
    "puede no aparecer. Una MAC o un fabricante reconocidos no demuestran que un equipo sea seguro."
)


class _TablaDispositivos(QTableWidget):
    def __init__(self) -> None:
        super().__init__(0, len(COLUMNAS))
        self.setObjectName("tablaDispositivos")
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


class DeviceView(PaginaBase):
    revisarSolicitado = Signal(str)   # MAC

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Dispositivos", "Identificación en tiempo real", parent)
        panel = Panel("Dispositivos conectados")
        panel.titulo.setToolTip(AYUDA_LIMITACIONES)
        self._pila = QStackedWidget()
        self._tabla = _TablaDispositivos()
        self._mensaje = QLabel()
        self._mensaje.setObjectName("mensajeTabla")
        self._mensaje.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mensaje.setWordWrap(True)
        self._pila.addWidget(self._tabla)
        self._pila.addWidget(self._mensaje)
        panel.diseno.addWidget(self._pila, 1)
        self.contenido.addWidget(panel, 1)
        self.mostrar_mensaje("Iniciando…")

    # --- API usada por DeviceController -----------------------------------
    @property
    def filas(self) -> int:
        return self._tabla.rowCount() if self._pila.currentWidget() is self._tabla else 0

    def mostrar_mensaje(self, texto: str, error: bool = False) -> None:
        self._tabla.setRowCount(0)
        self._mensaje.setText(texto)
        self._mensaje.setProperty("error", "true" if error else "false")
        repulir(self._mensaje)
        self._pila.setCurrentWidget(self._mensaje)

    def mostrar_busqueda(self, nombre_interfaz: str) -> None:
        if self.filas == 0:
            destino = f" en «{nombre_interfaz}»" if nombre_interfaz else ""
            self.mostrar_mensaje(f"Buscando dispositivos{destino}… "
                                 "El primer barrido puede tardar unos segundos.")

    def mostrar_dispositivos(self, dispositivos: list[PerfilDispositivo]) -> None:
        if not dispositivos:
            self.mostrar_mensaje("Ningún dispositivo respondió en el último ciclo de descubrimiento.")
            return
        self._tabla.setRowCount(len(dispositivos))
        for fila, perfil in enumerate(dispositivos):
            self._llenar_fila(fila, perfil)
        self._pila.setCurrentWidget(self._tabla)

    def solicitar_decision(self, perfil: PerfilDispositivo) -> tuple[str | None, str | None]:
        """Abre el diálogo «Revisar». Devuelve (accion, alias).

        accion ∈ {ACCION_AUTORIZAR, ACCION_AISLAR, None (cancelado)}.
        """
        dialogo = RevisarDispositivoDialog(perfil, self)
        dialogo.exec()
        return dialogo.accion, dialogo.alias()

    def confirmar_aislamiento(self, perfil: PerfilDispositivo) -> bool:
        respuesta = QMessageBox.warning(
            self, "Confirmar aislamiento",
            f"Se aislará de la red el dispositivo:\n\n"
            f"    IP:  {perfil.ip or formato.NO_DISPONIBLE}\n"
            f"    MAC: {perfil.mac}\n\n"
            "El dispositivo perderá la conectividad con la red local e Internet "
            "según el mecanismo de aislamiento implementado. ¿Desea continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return respuesta == QMessageBox.StandardButton.Yes

    def informar(self, titulo: str, texto: str) -> None:
        QMessageBox.information(self, titulo, texto)

    def advertir(self, titulo: str, texto: str) -> None:
        QMessageBox.warning(self, titulo, texto)

    # --- Interno -----------------------------------------------------------
    def _item(self, texto: str, ayuda: str | None = None, negrita: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(texto)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if ayuda:
            item.setToolTip(ayuda)
        if negrita:
            item.setFont(fuente_negrita())
            item.setForeground(QColor(TEXTO))
        return item

    def _llenar_fila(self, fila: int, perfil: PerfilDispositivo) -> None:
        self._tabla.setItem(fila, 0, self._item(formato.texto_nombre(perfil),
                                                formato.ayuda_nombre(perfil), negrita=True))
        self._tabla.setItem(fila, 1, self._item(perfil.ip or formato.NO_DISPONIBLE))
        self._tabla.setItem(fila, 2, self._item(perfil.mac))
        self._tabla.setItem(fila, 3, self._item(formato.texto_fabricante(perfil),
                                                formato.ayuda_fabricante(perfil)))
        self._tabla.setItem(fila, 4, self._item(perfil.estado.value))
        self._tabla.setItem(fila, 5, QTableWidgetItem())
        self._tabla.setCellWidget(fila, 5, self._celda_accion(perfil))

    def _celda_accion(self, perfil: PerfilDispositivo) -> QWidget:
        celda = QWidget()
        celda.setObjectName("celdaAccion")
        celda.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        diseno = QHBoxLayout(celda)
        diseno.setContentsMargins(14, 0, 0, 0)
        # Toda fila visible es un dispositivo detectado, no autorizado y no
        # aislado (los demás se excluyen en el servicio): la acción es «Revisar».
        boton = QPushButton("Revisar")
        boton.setObjectName("accionTabla")
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        boton.setToolTip("Ver los datos detectados y decidir si se autoriza o se aísla.")
        boton.clicked.connect(lambda _=False, mac=perfil.mac: self.revisarSolicitado.emit(mac))
        diseno.addWidget(boton)
        diseno.addStretch(1)
        return celda
