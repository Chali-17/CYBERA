"""Vista «Resumen» (Mockup 02): estado general de la red local.

- Cuatro tarjetas: dispositivos detectados, confiables, desconocidos y aislados.
- Panel «Actividad reciente» a todo lo ancho con los últimos eventos de la
  bitácora (hora, evento, IP o MAC e insignia de estado).

La vista solo dibuja datos ya preparados por ``ResumenController``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from presentation.widgets import Panel, PaginaBase, repulir

SIN_ACTIVIDAD = ("Aún no hay actividad registrada. Los eventos de conexión, autorización y "
                 "aislamiento aparecerán aquí.")


@dataclass(frozen=True)
class Indicadores:
    detectados: int
    confiables: int
    desconocidos: int
    aislados: int
    nota_detectados: str = "en el segmento monitoreado"


@dataclass(frozen=True)
class FilaActividad:
    """Un evento ya formateado (lo prepara ResumenController)."""

    hora: str
    titulo: str
    detalle: str              # IP (o MAC) y nombre, si se conoce
    insignia: str
    tono: str                 # naranja | verde | rojo | azul | ambar | gris
    ayuda: str = ""


class _Tarjeta(QFrame):
    def __init__(self, titulo: str, nota: str) -> None:
        super().__init__()
        self.setObjectName("tarjetaResumen")
        # Las cuatro tarjetas reparten el ancho por igual, sin importar el texto.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        diseno = QVBoxLayout(self)
        diseno.setContentsMargins(24, 18, 24, 18)
        diseno.setSpacing(4)
        etiqueta = QLabel(titulo)
        etiqueta.setObjectName("tituloTarjeta")
        self.valor = QLabel("—")
        self.valor.setObjectName("valorTarjeta")
        self.nota = QLabel(nota)
        self.nota.setObjectName("notaTarjeta")
        diseno.addWidget(etiqueta)
        diseno.addWidget(self.valor)
        diseno.addWidget(self.nota)

    def mostrar(self, valor: int, nota: str | None = None) -> None:
        self.valor.setText(str(valor))
        if nota is not None:
            self.nota.setText(nota)


class ResumenView(PaginaBase):
    mostrada = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Resumen", "Estado general de la red local", parent)

        # --- Tarjetas de indicadores -------------------------------------------
        fila_tarjetas = QHBoxLayout()
        fila_tarjetas.setSpacing(26)
        self.tarjeta_detectados = _Tarjeta("Dispositivos detectados", "en el segmento monitoreado")
        self.tarjeta_confiables = _Tarjeta("Confiables", "registrados en lista blanca")
        self.tarjeta_desconocidos = _Tarjeta("Desconocidos", "requieren revisión")
        self.tarjeta_aislados = _Tarjeta("Aislados", "contención activa")
        for tarjeta in (self.tarjeta_detectados, self.tarjeta_confiables,
                        self.tarjeta_desconocidos, self.tarjeta_aislados):
            fila_tarjetas.addWidget(tarjeta, 1)
        self.contenido.addLayout(fila_tarjetas)
        self.contenido.addSpacing(10)

        # --- Actividad reciente (ocupa todo el ancho) ---------------------------
        panel = Panel("Actividad reciente")
        self._pila = QStackedWidget()
        self._lista = QScrollArea()
        self._lista.setObjectName("listaActividad")
        self._lista.setWidgetResizable(True)
        self._lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._contenedor = QWidget()
        self._contenedor.setObjectName("contenedorActividad")
        self._filas_diseno = QVBoxLayout(self._contenedor)
        self._filas_diseno.setContentsMargins(0, 4, 0, 0)
        self._filas_diseno.setSpacing(8)
        self._lista.setWidget(self._contenedor)
        self._mensaje = QLabel()
        self._mensaje.setObjectName("mensajeTabla")
        self._mensaje.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mensaje.setWordWrap(True)
        self._pila.addWidget(self._lista)
        self._pila.addWidget(self._mensaje)
        panel.diseno.addWidget(self._pila, 1)
        self.contenido.addWidget(panel, 1)

        self._filas: list[FilaActividad] = []
        self.mostrar_mensaje("Cargando actividad reciente…")

    # --- Eventos -------------------------------------------------------------
    def showEvent(self, evento) -> None:  # noqa: N802 - API de Qt
        super().showEvent(evento)
        self.mostrada.emit()

    # --- API usada por ResumenController -------------------------------------
    def mostrar_indicadores(self, datos: Indicadores) -> None:
        self.tarjeta_detectados.mostrar(datos.detectados, datos.nota_detectados)
        self.tarjeta_confiables.mostrar(datos.confiables)
        self.tarjeta_desconocidos.mostrar(datos.desconocidos)
        self.tarjeta_aislados.mostrar(datos.aislados)

    def mostrar_actividad(self, filas: list[FilaActividad]) -> None:
        if not filas:
            self.mostrar_mensaje(SIN_ACTIVIDAD)
            return
        self._limpiar()
        self._filas = list(filas)
        for fila in filas:
            self._filas_diseno.addWidget(self._fila(fila))
        self._filas_diseno.addStretch(1)
        self._pila.setCurrentWidget(self._lista)

    def mostrar_mensaje(self, texto: str, error: bool = False) -> None:
        self._limpiar()
        self._mensaje.setText(texto)
        self._mensaje.setProperty("error", "true" if error else "false")
        repulir(self._mensaje)
        self._pila.setCurrentWidget(self._mensaje)

    def filas(self) -> list[FilaActividad]:
        return list(self._filas) if self._pila.currentWidget() is self._lista else []

    # --- Interno -------------------------------------------------------------
    def _limpiar(self) -> None:
        self._filas = []
        while self._filas_diseno.count():
            elemento = self._filas_diseno.takeAt(0)
            if elemento.widget() is not None:
                elemento.widget().deleteLater()

    @staticmethod
    def _fila(fila: FilaActividad) -> QWidget:
        contenedor = QWidget()
        contenedor.setObjectName("filaActividad")
        diseno = QHBoxLayout(contenedor)
        diseno.setContentsMargins(40, 10, 40, 10)
        diseno.setSpacing(16)

        textos = QVBoxLayout()
        textos.setSpacing(6)
        titulo = QLabel(f"{fila.hora}  {fila.titulo}")
        titulo.setObjectName("tituloActividad")
        detalle = QLabel(fila.detalle)
        detalle.setObjectName("detalleActividad")
        detalle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        textos.addWidget(titulo)
        textos.addWidget(detalle)
        diseno.addLayout(textos, 1)

        insignia = QLabel(fila.insignia)
        insignia.setObjectName("insigniaActividad")
        insignia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        insignia.setProperty("tono", fila.tono)
        if fila.ayuda:
            insignia.setToolTip(fila.ayuda)
            titulo.setToolTip(fila.ayuda)
        diseno.addWidget(insignia, 0, Qt.AlignmentFlag.AlignVCenter)
        return contenedor
