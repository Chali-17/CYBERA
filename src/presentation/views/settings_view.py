"""Vista «Configuración» (Mockup 09 + sección de red y monitoreo).

- «Red y monitoreo»: funcional (interfaz real y activación del monitoreo).
- «Notificaciones externas»: réplica visual del Mockup 09 SIN acciones
  (pendiente de CU-02); sus controles están deshabilitados.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from app.models.interfaz_red import InterfazRed
from app.services.monitoring_service import INTERVALO_ESCANEO_S
from presentation.widgets import Panel, PaginaBase, repulir

_PENDIENTE = "Pendiente de implementación: notificaciones externas (CU-02)."


def _etiqueta(texto: str, nombre: str = "etiquetaCampo") -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setObjectName(nombre)
    return etiqueta


def texto_interfaz(interfaz: InterfazRed) -> str:
    tipo = interfaz.tipo.etiqueta + (" virtual" if interfaz.virtual else "")
    direccion = f"{interfaz.ipv4}/{interfaz.prefijo}" if interfaz.ipv4 else "sin IPv4"
    estado = "Conectada" if interfaz.conectada else "Desconectada"
    return f"{interfaz.nombre}  —  {tipo}  —  {direccion}  —  {estado}"


class SettingsView(PaginaBase):
    mostrada = Signal()
    interfazElegida = Signal(str)     # id de la interfaz
    alternarMonitoreo = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Configuración", "Parámetros del sistema y notificaciones",
                         "CYBERA • Mockup 09", parent)
        self._interfaces: dict[str, InterfazRed] = {}

        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        interior = QWidget()
        interior.setObjectName("contenidoDesplazable")
        columna = QVBoxLayout(interior)
        columna.setContentsMargins(0, 0, 6, 0)
        columna.setSpacing(22)
        columna.addWidget(self._crear_panel_red())
        columna.addWidget(self._crear_panel_notificaciones())
        columna.addStretch(1)
        desplazable.setWidget(interior)
        self.contenido.addWidget(desplazable, 1)

    # --- Construcción ------------------------------------------------------
    def _crear_panel_red(self) -> Panel:
        panel = Panel("Red y monitoreo")
        rejilla = QGridLayout()
        rejilla.setContentsMargins(14, 8, 14, 0)
        rejilla.setHorizontalSpacing(24)
        rejilla.setVerticalSpacing(10)

        rejilla.addWidget(_etiqueta("Interfaz de red"), 0, 0)
        self.combo_interfaz = QComboBox()
        self.combo_interfaz.setObjectName("campo")
        self.combo_interfaz.setCursor(Qt.CursorShape.PointingHandCursor)
        # Vista estilizada para el desplegable: así las opciones se ven con la
        # altura correcta y sin el área blanca gigante del popup nativo.
        lista = QListView()
        lista.setObjectName("listaInterfaces")
        lista.setUniformItemSizes(True)
        self.combo_interfaz.setView(lista)
        self.combo_interfaz.setMaxVisibleItems(8)
        # El texto seleccionado no debe quedar cortado aunque sea largo.
        self.combo_interfaz.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo_interfaz.setMinimumContentsLength(24)
        self.combo_interfaz.activated.connect(self._al_elegir)
        self.combo_interfaz.currentIndexChanged.connect(self._actualizar_ayuda)
        rejilla.addWidget(self.combo_interfaz, 1, 0)
        self.ayuda_interfaz = _etiqueta("", "ayuda")
        self.ayuda_interfaz.setWordWrap(True)
        rejilla.addWidget(self.ayuda_interfaz, 2, 0)

        rejilla.addWidget(_etiqueta("Monitoreo"), 3, 0)
        self.estado_monitoreo = _etiqueta("", "estadoMonitoreo")
        self.estado_monitoreo.setWordWrap(True)
        rejilla.addWidget(self.estado_monitoreo, 4, 0)
        self.boton_monitoreo = QPushButton("Activar monitoreo")
        self.boton_monitoreo.setObjectName("botonVerde")
        self.boton_monitoreo.setProperty("funcional", "true")
        self.boton_monitoreo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_monitoreo.clicked.connect(self.alternarMonitoreo.emit)
        rejilla.addWidget(self.boton_monitoreo, 4, 1, Qt.AlignmentFlag.AlignLeft)

        self.aviso = _etiqueta("", "aviso")
        self.aviso.setWordWrap(True)
        self.aviso.hide()
        rejilla.addWidget(self.aviso, 5, 0, 1, 2)
        rejilla.setColumnStretch(0, 3)
        rejilla.setColumnStretch(1, 2)
        panel.diseno.addLayout(rejilla)
        return panel

    def _crear_panel_notificaciones(self) -> Panel:
        panel = Panel("Notificaciones externas")
        panel.setToolTip(_PENDIENTE)
        rejilla = QGridLayout()
        rejilla.setContentsMargins(14, 8, 14, 0)
        rejilla.setHorizontalSpacing(24)
        rejilla.setVerticalSpacing(10)

        rejilla.addWidget(_etiqueta("Canal de mensajería"), 0, 0)
        canales = QHBoxLayout()
        canales.setSpacing(20)
        for texto, activo in (("Telegram", True), ("WhatsApp", False), ("Correo", False)):
            boton = QPushButton(texto)
            boton.setObjectName("canalActivo" if activo else "canal")
            boton.setEnabled(False)
            boton.setToolTip(_PENDIENTE)
            canales.addWidget(boton)
        canales.addStretch(1)
        rejilla.addLayout(canales, 1, 0)
        rejilla.setRowMinimumHeight(2, 18)

        rejilla.addWidget(_etiqueta("Token / credencial"), 3, 0)
        token = QLineEdit()
        token.setObjectName("campo")
        token.setEchoMode(QLineEdit.EchoMode.Password)
        token.setEnabled(False)
        token.setToolTip(_PENDIENTE)
        rejilla.addWidget(token, 4, 0)
        rejilla.setRowMinimumHeight(5, 14)

        rejilla.addWidget(_etiqueta("Identificador de destino"), 6, 0)
        destino = QLineEdit()
        destino.setObjectName("campo")
        destino.setPlaceholderText("chat_id / correo")
        destino.setEnabled(False)
        destino.setToolTip(_PENDIENTE)
        rejilla.addWidget(destino, 7, 0)
        acciones = QHBoxLayout()
        acciones.setSpacing(24)
        for texto, nombre in (("Probar conexión", "botonAzul"), ("Guardar", "botonVerde")):
            boton = QPushButton(texto)
            boton.setObjectName(nombre)
            boton.setEnabled(False)
            boton.setToolTip(_PENDIENTE)
            acciones.addWidget(boton)
        acciones.addStretch(1)
        rejilla.addLayout(acciones, 7, 1)
        rejilla.setColumnStretch(0, 3)
        rejilla.setColumnStretch(1, 2)
        panel.diseno.addLayout(rejilla)
        panel.diseno.addSpacing(24)
        return panel

    # --- Eventos -----------------------------------------------------------
    def showEvent(self, evento) -> None:  # noqa: N802 - API de Qt
        super().showEvent(evento)
        self.mostrada.emit()

    def _al_elegir(self, indice: int) -> None:
        interfaz_id = self.combo_interfaz.itemData(indice)
        if interfaz_id:
            self.interfazElegida.emit(interfaz_id)

    def _actualizar_ayuda(self, indice: int) -> None:
        interfaz = self._interfaces.get(self.combo_interfaz.itemData(indice) or "")
        if interfaz is None:
            self.ayuda_interfaz.setText("")
            return
        partes = [interfaz.descripcion]
        if interfaz.mac:
            partes.append(f"MAC {interfaz.mac}")
        if interfaz.puerta_enlace:
            partes.append(f"Puerta de enlace {interfaz.puerta_enlace}")
        motivo = interfaz.motivo_no_utilizable()
        if motivo:
            partes.append(motivo)
        self.ayuda_interfaz.setText("  ·  ".join(p for p in partes if p))

    # --- API usada por SettingsController ---------------------------------
    def mostrar_cargando_interfaces(self) -> None:
        if self.combo_interfaz.count() == 0:
            self.combo_interfaz.addItem("Buscando interfaces de red…")
            self.combo_interfaz.setEnabled(False)

    def mostrar_error_interfaces(self, texto: str) -> None:
        self.combo_interfaz.clear()
        self.combo_interfaz.addItem("No se pudieron obtener las interfaces")
        self.combo_interfaz.setEnabled(False)
        self.mostrar_aviso(texto, exito=False)

    def mostrar_interfaces(self, interfaces: list[InterfazRed], seleccion_id: str | None,
                           nombre_guardado: str | None) -> None:
        self._interfaces = {i.id: i for i in interfaces}
        self.combo_interfaz.blockSignals(True)
        self.combo_interfaz.clear()
        if seleccion_id is None:
            self.combo_interfaz.addItem("Seleccione una interfaz…", None)
        for interfaz in interfaces:
            self.combo_interfaz.addItem(texto_interfaz(interfaz), interfaz.id)
        if seleccion_id and seleccion_id not in self._interfaces:
            self.combo_interfaz.addItem(f"{nombre_guardado or seleccion_id}  —  no disponible",
                                        seleccion_id)
        indice = self.combo_interfaz.findData(seleccion_id) if seleccion_id else 0
        self.combo_interfaz.setCurrentIndex(max(indice, 0))
        self.combo_interfaz.blockSignals(False)
        self.combo_interfaz.setEnabled(True)
        self._actualizar_ayuda(self.combo_interfaz.currentIndex())

    def mostrar_estado_monitoreo(self, activo: bool, hay_interfaz: bool) -> None:
        if activo:
            self.estado_monitoreo.setText(
                f"Activo: se buscan dispositivos cada {INTERVALO_ESCANEO_S} segundos, "
                "solo en la interfaz seleccionada.")
            self.boton_monitoreo.setText("Desactivar monitoreo")
            self.boton_monitoreo.setObjectName("botonNeutro")
            self.boton_monitoreo.setEnabled(True)
        else:
            self.estado_monitoreo.setText("Inactivo: no se realizan escaneos de la red."
                                          if hay_interfaz else
                                          "Inactivo. Seleccione una interfaz para poder activarlo.")
            self.boton_monitoreo.setText("Activar monitoreo")
            self.boton_monitoreo.setObjectName("botonVerde")
            self.boton_monitoreo.setEnabled(hay_interfaz)
        repulir(self.boton_monitoreo)

    def mostrar_aviso(self, texto: str, exito: bool) -> None:
        self.aviso.setText(("✓ " if exito else "") + texto)
        self.aviso.setProperty("exito", "true" if exito else "false")
        repulir(self.aviso)
        self.aviso.show()
