"""Vista «Aislamiento» (Mockup 06): dispositivos bajo contención y su desbloqueo.

Reproduce el Mockup 06 sin controles adicionales: encabezado (título, subtítulo,
indicador de monitoreo), panel «Dispositivos aislados» y una tarjeta por
dispositivo con nombre, IP, MAC, fecha, insignia de estado y botón «Desbloquear».

La insignia distingue estados (ver ``formato.insignia_aislamiento``); el texto
completo y no ambiguo de la situación se muestra como ayuda emergente.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from presentation.widgets import Panel, PaginaBase, repulir

SIN_DISPOSITIVOS = ("No hay dispositivos aislados ni pendientes de recuperación. Para aislar un "
                    "equipo, use «Revisar» → «Aislar» en Dispositivos.")


@dataclass(frozen=True)
class FilaAislamiento:
    """Datos ya formateados de una tarjeta (los prepara IsolationController)."""

    mac: str
    nombre: str
    ip: str
    fecha: str
    insignia: str
    tono: str                  # rojo | ambar | gris
    ayuda: str                 # Texto completo de la situación
    puede_desbloquear: bool
    # Sólo para situaciones «Requiere recuperación» bloqueadas: el operador puede
    # retirar el equipo del listado para que el escaneo lo detecte de nuevo.
    puede_quitar: bool = False


class IsolationView(PaginaBase):
    desbloquearSolicitado = Signal(str)      # MAC
    quitarSolicitado = Signal(str)          # MAC
    mostrada = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Aislamiento", "Gestión de dispositivos bajo contención", parent)
        panel = Panel("Dispositivos aislados")
        self._pila = QStackedWidget()
        self._lista = QScrollArea()
        self._lista.setObjectName("listaAislamiento")
        self._lista.setWidgetResizable(True)
        self._lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._contenedor = QWidget()
        self._contenedor.setObjectName("contenedorAislamiento")
        self._filas_diseno = QVBoxLayout(self._contenedor)
        self._filas_diseno.setContentsMargins(0, 8, 0, 0)
        self._filas_diseno.setSpacing(28)
        self._lista.setWidget(self._contenedor)
        self._mensaje = QLabel()
        self._mensaje.setObjectName("mensajeTabla")
        self._mensaje.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mensaje.setWordWrap(True)
        self._pila.addWidget(self._lista)
        self._pila.addWidget(self._mensaje)
        panel.diseno.addWidget(self._pila, 1)
        self.contenido.addWidget(panel, 1)
        self._filas: list[FilaAislamiento] = []
        self._botones: dict[str, QPushButton] = {}
        self._botones_quitar: dict[str, QPushButton] = {}
        self._insignias: dict[str, QLabel] = {}
        self.mostrar_mensaje("Cargando dispositivos bajo contención…")

    # --- Eventos -----------------------------------------------------------
    def showEvent(self, evento) -> None:  # noqa: N802 - API de Qt
        super().showEvent(evento)
        self.mostrada.emit()

    # --- API usada por IsolationController ---------------------------------
    def mostrar_mensaje(self, texto: str, error: bool = False) -> None:
        self._limpiar()
        self._mensaje.setText(texto)
        self._mensaje.setProperty("error", "true" if error else "false")
        repulir(self._mensaje)
        self._pila.setCurrentWidget(self._mensaje)

    def mostrar_filas(self, filas: list[FilaAislamiento]) -> None:
        if not filas:
            self.mostrar_mensaje(SIN_DISPOSITIVOS)
            return
        self._limpiar()
        self._filas = list(filas)
        for fila in filas:
            self._filas_diseno.addWidget(self._tarjeta(fila))
        self._filas_diseno.addStretch(1)
        self._pila.setCurrentWidget(self._lista)

    def filas(self) -> list[FilaAislamiento]:
        return list(self._filas) if self._pila.currentWidget() is self._lista else []

    def boton_desbloquear(self, mac: str) -> QPushButton | None:
        return self._botones.get(mac)

    def boton_quitar(self, mac: str) -> QPushButton | None:
        return self._botones_quitar.get(mac)

    def insignia(self, mac: str) -> QLabel | None:
        return self._insignias.get(mac)

    def confirmar_desbloqueo(self, nombre: str, mac: str, ip: str, recuperacion: bool) -> bool:
        aviso = ("El último resultado es INCIERTO: se pedirá al motor que retire cualquier "
                 "contención y se verificará la respuesta.\n\n" if recuperacion else "")
        respuesta = QMessageBox.question(
            self, "Confirmar desbloqueo",
            f"Se solicitará retirar la contención del dispositivo:\n\n"
            f"    Nombre: {nombre}\n    MAC:    {mac}\n    IP:     {ip}\n\n{aviso}"
            "Solo se dará por desbloqueado si el motor de red confirma que ya no aplica "
            "contención. ¿Desea continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return respuesta == QMessageBox.StandardButton.Yes

    def confirmar_quitar(self, nombre: str, mac: str, ip: str) -> bool:
        """Confirma la acción manual de «Quitar de la lista» para una situación
        «Requiere recuperación» bloqueada."""
        respuesta = QMessageBox.question(
            self, "Quitar de la lista",
            f"¿Quiere retirar del listado de aislamiento al dispositivo?\n\n"
            f"    Nombre: {nombre}\n    MAC:    {mac}\n    IP:     {ip}\n\n"
            "El equipo dejará de figurar como aislado y podrá volver a ser detectado por el "
            "escaneo. Esta acción sólo aplica a una situación «Requiere recuperación».",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return respuesta == QMessageBox.StandardButton.Yes

    def informar(self, titulo: str, texto: str) -> None:
        QMessageBox.information(self, titulo, texto)

    def advertir(self, titulo: str, texto: str) -> None:
        QMessageBox.warning(self, titulo, texto)

    # --- Interno -----------------------------------------------------------
    def _limpiar(self) -> None:
        self._filas = []
        self._botones.clear()
        self._botones_quitar.clear()
        self._insignias.clear()
        while self._filas_diseno.count():
            elemento = self._filas_diseno.takeAt(0)
            if elemento.widget() is not None:
                elemento.widget().deleteLater()

    def _tarjeta(self, fila: FilaAislamiento) -> QFrame:
        # Como en el Mockup 06: datos y acciones en la parte superior de la tarjeta.
        tarjeta = QFrame()
        tarjeta.setObjectName("filaAislamiento")
        tarjeta.setMinimumHeight(118)
        exterior = QVBoxLayout(tarjeta)
        exterior.setContentsMargins(36, 14, 6, 14)
        fila_datos = QHBoxLayout()
        fila_datos.setSpacing(0)
        exterior.addLayout(fila_datos)
        exterior.addStretch(1)

        for texto, nombre_objeto, ancho in [(fila.nombre, "nombreFila", 268),
                                            (fila.ip, None, 200),
                                            (fila.mac, None, 288),
                                            (fila.fecha, "fechaFila", 200)]:
            etiqueta = QLabel(texto)
            if nombre_objeto:
                etiqueta.setObjectName(nombre_objeto)
            etiqueta.setMinimumWidth(ancho // 2)
            etiqueta.setMaximumWidth(ancho)
            etiqueta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            fila_datos.addWidget(etiqueta, 1)
        fila_datos.addStretch(1)

        insignia = QLabel(fila.insignia)
        insignia.setObjectName("insigniaAislamiento")
        insignia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        insignia.setProperty("tono", fila.tono)
        insignia.setToolTip(fila.ayuda)
        fila_datos.addWidget(insignia)
        fila_datos.addSpacing(20)

        boton = QPushButton("Desbloquear")
        boton.setObjectName("botonAzul")
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        boton.setEnabled(fila.puede_desbloquear)
        boton.setToolTip(fila.ayuda)
        boton.clicked.connect(lambda _=False, m=fila.mac: self.desbloquearSolicitado.emit(m))
        fila_datos.addWidget(boton)
        if fila.puede_quitar:
            # Opción del operador para una situación «Requiere recuperación» bloqueada:
            # saca el equipo del listado para que el escaneo lo detecte de nuevo.
            boton_quitar = QPushButton("Quitar de la lista")
            boton_quitar.setObjectName("botonRojo")
            boton_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
            boton_quitar.setToolTip("Retirar el equipo del listado de aislamiento (sólo para una "
                                   "situación «Requiere recuperación») para que el escaneo lo "
                                   "pueda detectar de nuevo.")
            boton_quitar.clicked.connect(lambda _=False, m=fila.mac: self.quitarSolicitado.emit(m))
            fila_datos.addWidget(boton_quitar)

        self._botones[fila.mac] = boton
        if fila.puede_quitar:
            self._botones_quitar[fila.mac] = boton_quitar
        self._insignias[fila.mac] = insignia
        return tarjeta
