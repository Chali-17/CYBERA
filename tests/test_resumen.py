"""Pruebas de la pantalla Resumen (Mockup 02): indicadores y actividad reciente."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from PySide6.QtWidgets import QLabel

from app.controllers.resumen_controller import ResumenController
from app.models.evento_bitacora import EventoBitacora, ResultadoEvento, TipoEvento, nuevo_id
from presentation.views.resumen_view import SIN_ACTIVIDAD, ResumenView

MAC_A = "AA:AA:AA:AA:AA:01"
MAC_B = "BB:BB:BB:BB:BB:02"


class Monitoreo:
    def __init__(self, detectados=0, desconocidos=0):
        self.detectados, self.desconocidos = detectados, desconocidos

    def cantidad_detectados(self):
        return self.detectados

    def reclasificar(self):
        return [object()] * self.desconocidos


class ListaBlanca:
    def __init__(self, registros=None):
        self.registros = registros or {}

    def autorizados(self):
        return dict(self.registros)


class Aislamiento:
    def __init__(self, macs=()):
        self.macs = set(macs)

    def macs_aisladas(self):
        return set(self.macs)


class Bitacora:
    def __init__(self, eventos=(), error=None):
        self.eventos, self.error = list(eventos), error

    def historial(self):
        if self.error:
            raise self.error
        return sorted(self.eventos, key=lambda e: e.fecha_hora, reverse=True)


def evento(tipo, mac, minutos=0, ip=None, resultado=None, nombre=None):
    return EventoBitacora(id=nuevo_id(), tipo=tipo, mac_dispositivo=mac, ip_dispositivo=ip,
                          nombre_dispositivo=nombre, resultado=resultado,
                          fecha_hora=datetime.now().replace(microsecond=0) - timedelta(minutes=minutos))


def pantalla(qapp, monitoreo=None, lista=None, aislamiento=None, bitacora=None):
    vista = ResumenView()
    ctrl = ResumenController(vista, monitoreo or Monitoreo(), lista or ListaBlanca(),
                             aislamiento or Aislamiento(), bitacora or Bitacora())
    ctrl.recargar()
    return vista, ctrl


def test_sin_pie_de_mockup_ni_panel_de_estado(qapp):
    vista, _ = pantalla(qapp)
    textos = {e.text() for e in vista.findChildren(QLabel)}
    assert {"Resumen", "Estado general de la red local", "Actividad reciente"} <= textos
    assert "Estado del monitoreo" not in textos
    assert not any("Mockup" in t for t in textos)
    assert SIN_ACTIVIDAD in textos


def test_indicadores_con_datos_reales(qapp):
    lista = ListaBlanca({MAC_A: SimpleNamespace(alias="Laptop"), MAC_B: SimpleNamespace(alias=None)})
    vista, _ = pantalla(qapp, Monitoreo(detectados=12, desconocidos=2), lista,
                        Aislamiento([MAC_B]))
    assert vista.tarjeta_detectados.valor.text() == "12"
    assert vista.tarjeta_confiables.valor.text() == "2"
    assert vista.tarjeta_desconocidos.valor.text() == "2"
    assert vista.tarjeta_aislados.valor.text() == "1"


def test_actividad_reciente_ordenada_y_con_insignias(qapp):
    eventos = [
        evento(TipoEvento.DESCONEXION, MAC_B, minutos=20),
        evento(TipoEvento.BLOQUEO, MAC_A, minutos=10, resultado=ResultadoEvento.EXITOSO),
        evento(TipoEvento.AUTORIZACION_DISPOSITIVO, MAC_B, minutos=5, resultado=ResultadoEvento.EXITOSO),
        evento(TipoEvento.CONEXION, MAC_A, minutos=1, ip="192.168.1.25"),
        evento(TipoEvento.DESBLOQUEO, MAC_A, minutos=30, resultado=ResultadoEvento.FALLO),
    ]
    vista, _ = pantalla(qapp, bitacora=Bitacora(eventos))
    filas = vista.filas()
    assert [(f.titulo, f.insignia, f.tono) for f in filas] == [
        ("Nuevo dispositivo detectado", "Desconocido", "naranja"),
        ("Dispositivo autorizado", "Confiable", "verde"),
        ("Aislamiento aplicado", "Aislado", "rojo"),
        ("Dispositivo desconectado", "Finalizado", "gris"),
        ("Desbloqueo fallido", "Fallido", "ambar"),
    ]
    assert filas[0].detalle == "192.168.1.25"
    assert filas[2].detalle == MAC_A          # Sin IP registrada: se muestra la MAC.


def test_conexion_de_equipo_autorizado_se_muestra_confiable_con_alias(qapp):
    lista = ListaBlanca({MAC_A: SimpleNamespace(alias="Laptop")})
    vista, _ = pantalla(qapp, lista=lista, bitacora=Bitacora(
        [evento(TipoEvento.CONEXION, MAC_A, ip="192.168.1.18")]))
    fila = vista.filas()[0]
    assert (fila.insignia, fila.tono) == ("Confiable", "verde")
    assert fila.detalle == "192.168.1.18  ·  Laptop"


def test_error_de_bitacora_no_rompe_los_indicadores(qapp):
    vista, _ = pantalla(qapp, Monitoreo(detectados=3), bitacora=Bitacora(error=OSError("dañado")))
    assert vista.tarjeta_detectados.valor.text() == "3"
    assert vista.filas() == []
    textos = {e.text() for e in vista.findChildren(QLabel)}
    assert any("No se pudo leer la actividad reciente" in t for t in textos)
