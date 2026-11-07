"""Diálogo «Editar» de la Lista blanca: consulta y administración de un registro."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from app.models.dispositivo_confiable import LONGITUD_MAXIMA_ALIAS
from presentation import formato

ACCION_GUARDAR = "guardar"
ACCION_ELIMINAR = "eliminar"
ACCION_AISLAR = "aislar"


@dataclass
class DatosEdicion:
    """Datos para el diálogo. IP/fabricante/hostname provienen del equipo si está
    detectado ahora; si no, quedan en None (se muestran como «No disponible»)."""

    mac: str
    alias: str | None
    fecha_autorizacion: str
    ip: str | None = None
    fabricante: str | None = None
    hostname: str | None = None
    aislado: bool = False
    # Texto del estado de aislamiento (confirmado, solicitado, fallido...). Si no
    # se indica, se deriva de ``aislado``.
    estado_aislamiento: str | None = None


class EditarListaBlancaDialog(QDialog):
    def __init__(self, datos: DatosEdicion, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dialogoRevision")   # Reutiliza el estilo del diálogo.
        self.setWindowTitle("Editar dispositivo de confianza")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._accion: str | None = None

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(28, 24, 28, 22)
        raiz.setSpacing(14)
        titulo = QLabel("Dispositivo autorizado")
        titulo.setObjectName("tituloDialogo")
        raiz.addWidget(titulo)

        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(18)
        rejilla.setVerticalSpacing(8)
        filas = [
            ("Dirección MAC", datos.mac),
            ("Dirección IP", datos.ip or formato.NO_DISPONIBLE),
            ("Fabricante", datos.fabricante or formato.NO_DISPONIBLE),
            ("Nombre de host", datos.hostname or formato.NO_DISPONIBLE),
            ("Fecha de autorización", datos.fecha_autorizacion),
            ("Estado de autorización", "Confiable (en lista blanca)"),
            ("Estado de aislamiento", datos.estado_aislamiento
             or (formato.REGISTRADO_SIN_VERIFICAR if datos.aislado else formato.SIN_REGISTRO)),
        ]
        for fila, (clave, valor) in enumerate(filas):
            etiqueta = QLabel(clave)
            etiqueta.setObjectName("claveDato")
            dato = QLabel(valor)
            dato.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            rejilla.addWidget(etiqueta, fila, 0)
            rejilla.addWidget(dato, fila, 1)
        raiz.addLayout(rejilla)

        if datos.ip is None:
            nota = QLabel("La IP, el fabricante y el nombre de host se muestran solo si el "
                          "equipo está detectado en la red en este momento.")
            nota.setObjectName("ayuda")
            nota.setWordWrap(True)
            raiz.addWidget(nota)

        etiqueta_alias = QLabel("Alias")
        etiqueta_alias.setObjectName("claveDato")
        raiz.addWidget(etiqueta_alias)
        self._alias = QLineEdit()
        self._alias.setObjectName("campo")
        self._alias.setMaxLength(LONGITUD_MAXIMA_ALIAS)
        self._alias.setPlaceholderText("Ej.: Laptop de trabajo")
        if datos.alias:
            self._alias.setText(datos.alias)
        self._alias.returnPressed.connect(self._al_guardar)
        raiz.addWidget(self._alias)

        nota_mac = QLabel("La dirección MAC identifica el registro y no puede modificarse.")
        nota_mac.setObjectName("ayuda")
        nota_mac.setWordWrap(True)
        raiz.addWidget(nota_mac)

        botones = QHBoxLayout()
        eliminar = QPushButton("Eliminar de lista blanca")
        eliminar.setObjectName("botonRojoSuave")
        eliminar.clicked.connect(self._al_eliminar)
        botones.addWidget(eliminar)
        botones.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.setObjectName("botonNeutro")
        cancelar.clicked.connect(self.reject)
        aislar = QPushButton("Aislar")
        aislar.setObjectName("botonRojo")
        aislar.clicked.connect(self._al_aislar)
        guardar = QPushButton("Guardar")
        guardar.setObjectName("botonVerde")
        guardar.clicked.connect(self._al_guardar)
        for boton in (cancelar, aislar, guardar):
            botones.addWidget(boton)
        raiz.addSpacing(6)
        raiz.addLayout(botones)

    def _al_guardar(self) -> None:
        self._accion = ACCION_GUARDAR
        self.accept()

    def _al_eliminar(self) -> None:
        self._accion = ACCION_ELIMINAR
        self.accept()

    def _al_aislar(self) -> None:
        self._accion = ACCION_AISLAR
        self.accept()

    @property
    def accion(self) -> str | None:
        return self._accion if self.result() == QDialog.DialogCode.Accepted else None

    def alias(self) -> str | None:
        texto = self._alias.text().strip()
        return texto or None
