"""Diálogo «Revisar»: datos reales del dispositivo y confirmación de autorización (CU-04)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from app.models.dispositivo import PerfilDispositivo
from app.models.dispositivo_confiable import LONGITUD_MAXIMA_ALIAS
from presentation import formato

# Acciones que puede devolver el diálogo.
ACCION_AUTORIZAR = "autorizar"
ACCION_AISLAR = "aislar"


class RevisarDispositivoDialog(QDialog):
    def __init__(self, perfil: PerfilDispositivo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dialogoRevision")
        self.setWindowTitle("Revisar dispositivo")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._accion: str | None = None

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(28, 24, 28, 22)
        raiz.setSpacing(14)
        titulo = QLabel("Dispositivo no registrado en la lista blanca")
        titulo.setObjectName("tituloDialogo")
        raiz.addWidget(titulo)

        datos = QGridLayout()
        datos.setHorizontalSpacing(18)
        datos.setVerticalSpacing(8)
        filas = [
            ("Nombre de host", perfil.hostname or formato.NO_DISPONIBLE),
            ("Dirección IP", perfil.ip or formato.NO_DISPONIBLE),
            ("Dirección MAC", perfil.mac),
            ("Fabricante", formato.texto_fabricante(perfil)),
            ("Detección", perfil.fuente.value if perfil.fuente else formato.NO_DISPONIBLE),
            ("Primera detección", f"{perfil.primera_deteccion:%d/%m/%Y %H:%M:%S}"),
        ]
        for fila, (clave, valor) in enumerate(filas):
            etiqueta = QLabel(clave)
            etiqueta.setObjectName("claveDato")
            dato = QLabel(valor)
            dato.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            datos.addWidget(etiqueta, fila, 0)
            datos.addWidget(dato, fila, 1)
        raiz.addLayout(datos)

        notas = ["Una MAC o un fabricante reconocidos no demuestran que el dispositivo sea "
                 "seguro. Autorícelo solo si reconoce el equipo."]
        if perfil.mac_local:
            notas.append("Este equipo usa una MAC aleatoria: puede cambiarla en el futuro y "
                         "volver a aparecer como desconocido.")
        for texto in notas:
            nota = QLabel(texto)
            nota.setObjectName("nota")
            nota.setWordWrap(True)
            raiz.addWidget(nota)

        etiqueta_alias = QLabel("Alias (opcional)")
        etiqueta_alias.setObjectName("claveDato")
        raiz.addWidget(etiqueta_alias)
        self._alias = QLineEdit()
        self._alias.setObjectName("campo")
        self._alias.setMaxLength(LONGITUD_MAXIMA_ALIAS)
        self._alias.setPlaceholderText("Ej.: Laptop de trabajo")
        if perfil.hostname:
            self._alias.setText(perfil.hostname)
        raiz.addWidget(self._alias)

        botones = QHBoxLayout()
        botones.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.setObjectName("botonNeutro")
        cancelar.clicked.connect(self.reject)
        aislar = QPushButton("Aislar")
        aislar.setObjectName("botonRojo")
        aislar.setToolTip("Aislar el dispositivo de la red (acción de defensa activa).")
        aislar.clicked.connect(self._al_aislar)
        autorizar = QPushButton("Autorizar")
        autorizar.setObjectName("botonVerde")
        autorizar.clicked.connect(self._al_autorizar)
        cancelar.setDefault(True)   # Evita autorizar/aislar por pulsar Enter sin querer.
        botones.addWidget(cancelar)
        botones.addWidget(aislar)
        botones.addWidget(autorizar)
        raiz.addSpacing(6)
        raiz.addLayout(botones)

    def _al_autorizar(self) -> None:
        self._accion = ACCION_AUTORIZAR
        self.accept()

    def _al_aislar(self) -> None:
        self._accion = ACCION_AISLAR
        self.accept()

    @property
    def accion(self) -> str | None:
        """Acción elegida: ACCION_AUTORIZAR, ACCION_AISLAR o None si se canceló."""
        return self._accion if self.result() == QDialog.DialogCode.Accepted else None

    def alias(self) -> str | None:
        texto = self._alias.text().strip()
        return texto or None
