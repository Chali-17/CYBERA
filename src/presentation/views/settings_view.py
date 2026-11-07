"""Vista «Configuración» (Mockup 09 + sección de red y monitoreo).

- «Red y monitoreo»: funcional (interfaz real y activación del monitoreo).
- «Notificaciones por correo electrónico»: funcional. Pide solo el correo
  remitente y la contraseña de aplicación de Gmail; envía una alerta cuando se
  detectan dispositivos nuevos.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from app.models.interfaz_red import InterfazRed
from app.services.monitoring_service import INTERVALO_ESCANEO_S
from presentation.widgets import Panel, PaginaBase, repulir

_ESTADO_CORREO_TEXTO = {
    "configurado": "● Configurado",
    "no_configurado": "● No configurado",
    "error": "● Error de conexión",
    "cargando": "● Procesando…",
}


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
    guardarCorreoSolicitado = Signal(str, str)    # remitente, contraseña (puede ir vacía)
    probarCorreoSolicitado = Signal(str, str)     # remitente, contraseña (puede ir vacía)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Configuración", "Parámetros del sistema y notificaciones", parent)
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
        panel = Panel("Notificaciones por correo electrónico")
        descripcion = _etiqueta(
            "Recibe una alerta cuando se detecten nuevos dispositivos conectados a la red.", "ayuda")
        descripcion.setWordWrap(True)
        panel.diseno.addWidget(descripcion)

        rejilla = QGridLayout()
        rejilla.setContentsMargins(14, 10, 14, 0)
        rejilla.setHorizontalSpacing(24)
        rejilla.setVerticalSpacing(8)

        # --- Correo remitente --------------------------------------------------
        rejilla.addWidget(_etiqueta("Correo electrónico desde el que se enviarán las notificaciones"),
                          0, 0, 1, 2)
        self.correo_remitente = QLineEdit()
        self.correo_remitente.setObjectName("campo")
        self.correo_remitente.setPlaceholderText("usuario@gmail.com")
        self.correo_remitente.setClearButtonEnabled(True)
        rejilla.addWidget(self.correo_remitente, 1, 0, 1, 2)
        rejilla.setRowMinimumHeight(2, 12)

        # --- Contraseña de aplicación -----------------------------------------
        rejilla.addWidget(_etiqueta("Contraseña de aplicación de Gmail"), 3, 0, 1, 2)
        fila_pass = QHBoxLayout()
        fila_pass.setSpacing(12)
        self.correo_contrasena = QLineEdit()
        self.correo_contrasena.setObjectName("campo")
        self.correo_contrasena.setEchoMode(QLineEdit.EchoMode.Password)
        self.correo_contrasena.setPlaceholderText("Contraseña de aplicación de 16 caracteres")
        fila_pass.addWidget(self.correo_contrasena, 1)
        self.boton_ver_pass = QPushButton("Mostrar")
        self.boton_ver_pass.setObjectName("botonEditar")
        self.boton_ver_pass.setCheckable(True)
        self.boton_ver_pass.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_ver_pass.toggled.connect(self._alternar_ver_contrasena)
        fila_pass.addWidget(self.boton_ver_pass)
        rejilla.addLayout(fila_pass, 4, 0, 1, 2)

        self.ayuda_contrasena = _etiqueta(
            "Se requiere una contraseña de aplicación de Google (Cuenta de Google → Seguridad → "
            "Verificación en dos pasos → Contraseñas de aplicaciones). No es la contraseña habitual "
            "con la que inicia sesión en Gmail.", "ayuda")
        self.ayuda_contrasena.setWordWrap(True)
        rejilla.addWidget(self.ayuda_contrasena, 5, 0, 1, 2)
        rejilla.setRowMinimumHeight(6, 10)

        # --- Acciones y estado -------------------------------------------------
        acciones = QHBoxLayout()
        acciones.setSpacing(16)
        self.boton_guardar_correo = QPushButton("Guardar configuración")
        self.boton_guardar_correo.setObjectName("botonVerde")
        self.boton_guardar_correo.setProperty("funcional", "true")
        self.boton_guardar_correo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_guardar_correo.clicked.connect(self._guardar_correo)
        self.boton_probar_correo = QPushButton("Enviar correo de prueba")
        self.boton_probar_correo.setObjectName("botonAzul")
        self.boton_probar_correo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_probar_correo.clicked.connect(self._probar_correo)
        acciones.addWidget(self.boton_guardar_correo)
        acciones.addWidget(self.boton_probar_correo)
        acciones.addStretch(1)
        self.estado_correo = _etiqueta("● No configurado", "estadoCorreo")
        self.estado_correo.setProperty("tono", "no_configurado")
        acciones.addWidget(self.estado_correo, 0, Qt.AlignmentFlag.AlignVCenter)
        rejilla.addLayout(acciones, 7, 0, 1, 2)

        self.aviso_correo = _etiqueta("", "aviso")
        self.aviso_correo.setWordWrap(True)
        self.aviso_correo.hide()
        rejilla.addWidget(self.aviso_correo, 8, 0, 1, 2)
        rejilla.setColumnStretch(0, 3)
        rejilla.setColumnStretch(1, 2)
        panel.diseno.addLayout(rejilla)
        panel.diseno.addSpacing(16)
        return panel

    # --- Notificaciones por correo: interacción ----------------------------
    def _alternar_ver_contrasena(self, visible: bool) -> None:
        self.correo_contrasena.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self.boton_ver_pass.setText("Ocultar" if visible else "Mostrar")

    def _guardar_correo(self) -> None:
        self.guardarCorreoSolicitado.emit(self.correo_remitente.text(),
                                          self.correo_contrasena.text())

    def _probar_correo(self) -> None:
        self.probarCorreoSolicitado.emit(self.correo_remitente.text(),
                                         self.correo_contrasena.text())

    # --- Notificaciones por correo: API para NotificacionController --------
    def rellenar_correo(self, remitente: str | None, tiene_contrasena: bool) -> None:
        if not self.correo_remitente.hasFocus():
            self.correo_remitente.setText(remitente or "")
        marcador = ("Contraseña guardada (déjela vacía para conservarla)" if tiene_contrasena
                    else "Contraseña de aplicación de 16 caracteres")
        self.correo_contrasena.setPlaceholderText(marcador)

    def limpiar_contrasena(self) -> None:
        self.correo_contrasena.clear()
        if self.boton_ver_pass.isChecked():
            self.boton_ver_pass.setChecked(False)

    def set_correo_cargando(self, activo: bool, texto: str = "") -> None:
        for widget in (self.boton_guardar_correo, self.boton_probar_correo,
                       self.correo_remitente, self.correo_contrasena, self.boton_ver_pass):
            widget.setEnabled(not activo)
        if activo:
            self.estado_correo.setText(_ESTADO_CORREO_TEXTO["cargando"])
            self.estado_correo.setProperty("tono", "cargando")
            repulir(self.estado_correo)
            if texto:
                self.aviso_correo.setText(texto)
                self.aviso_correo.setProperty("exito", "true")
                repulir(self.aviso_correo)
                self.aviso_correo.show()

    def mostrar_estado_correo(self, estado: str, texto: str) -> None:
        self.estado_correo.setText(_ESTADO_CORREO_TEXTO.get(estado, "● No configurado"))
        self.estado_correo.setProperty("tono", estado)
        repulir(self.estado_correo)
        self.aviso_correo.setText(texto)
        self.aviso_correo.setProperty("exito", "false" if estado == "error" else "true")
        repulir(self.aviso_correo)
        self.aviso_correo.show()

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
