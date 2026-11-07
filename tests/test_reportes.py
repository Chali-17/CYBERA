"""Pruebas del módulo Reportes: exportación del historial de la bitácora a CSV y PDF."""

import csv
import io
import re
from datetime import date, datetime

import pytest

from app.controllers.reporte_controller import ReporteController
from app.models.evento_bitacora import EventoBitacora, ResultadoEvento, TipoEvento, nuevo_id
from app.services.bitacora_service import BitacoraService
from app.services.reporte_service import FORMATO_CSV, FORMATO_PDF, ReporteService
from infrastructure.persistence.bitacora_repository import JsonBitacoraRepository
from presentation.views.reporte_view import ReporteView

MAC_PC = "50:9A:4C:4C:78:B2"
T0 = datetime(2026, 10, 20, 12, 0, 0)


def _evento(tipo, descripcion="Dispositivo detectado en la red local.", resultado=None):
    return EventoBitacora(id=nuevo_id(), tipo=tipo, fecha_hora=T0, mac_dispositivo=MAC_PC,
                          nombre_dispositivo="PC", descripcion=descripcion, resultado=resultado)


def _reporte(tmp_path):
    return ReporteService(BitacoraService(JsonBitacoraRepository(tmp_path / "bitacora.json")),
                          directorio=tmp_path)


# --- Exportación CSV ---------------------------------------------------------------

def test_generar_csv_contiene_cabeceras_y_registros(tmp_path):
    reporte = _reporte(tmp_path)
    reporte._bitacora.registrar(TipoEvento.CONEXION, MAC_PC)
    reporte._bitacora.registrar(TipoEvento.BLOQUEO, MAC_PC, resultado=ResultadoEvento.EXITOSO)

    filas = list(csv.reader(io.StringIO(reporte.generar_csv(reporte.historial()))))
    assert filas[0] == ["Fecha y hora", "Evento", "Dispositivo", "IP", "Dirección MAC", "Resultado"]
    assert len(filas) == 3                                    # Cabecera + 2 eventos.
    assert filas[1][1] == "Conexión" and filas[2][1] == "Aislamiento"
    assert filas[2][5] == "Exitoso"
    assert filas[1][5] == "Registrado"


def test_generar_csv_escapa_comas_comillas_y_acentos(tmp_path):
    reporte = _reporte(tmp_path)
    reporte._bitacora.registrar(TipoEvento.CONEXION, MAC_PC, nombre_dispositivo='Equipo "X", y áéíóúñ 100%')
    filas = list(csv.reader(io.StringIO(reporte.generar_csv(reporte.historial()))))
    assert filas[1][2] == 'Equipo "X", y áéíóúñ 100%'


def test_generar_csv_protege_fórmulas_de_hoja_de_calculo(tmp_path):
    reporte = _reporte(tmp_path)
    reporte._bitacora.registrar(TipoEvento.CONEXION, MAC_PC, nombre_dispositivo="=SUMA(1+1)")
    contenido = reporte.generar_csv(reporte.historial())
    assert "'=SUMA(1+1)" in contenido                 # Se neutraliza la fórmula.


def test_guardar_csv_usa_utf8_bom_y_saltos_de_crlf(tmp_path):
    reporte = _reporte(tmp_path)
    reporte._bitacora.registrar(TipoEvento.CONEXION, MAC_PC)
    ruta = reporte.guardar_csv(reporte.historial())
    datos = ruta.read_bytes()
    assert ruta.name == "reporte_cybera_%s.csv" % date.today().strftime("%Y-%m-%d")
    assert datos.startswith(b"\xef\xbb\xbf")                    # BOM: compatible con Excel.
    assert b"\r\n" in datos                                        # Separador CRLF (RFC 4180).


# --- Exportación PDF ----------------------------------------------------------------

def test_generar_pdf_valido_y_multipagina(tmp_path):
    reporte = _reporte(tmp_path)
    eventos = [_evento(TipoEvento.CONEXION, descripcion="Dispositivo %d detectado en la red local." % i)
               for i in range(150)]
    datos = reporte.generar_pdf(eventos, tipo=[TipoEvento.CONEXION])
    assert datos.startswith(b"%PDF-")
    assert datos.rstrip().endswith(b"%%EOF")
    assert len(datos) > 0
    paginas = len(re.findall(rb"/Type\s*/Page[^s]", datos))
    assert paginas > 1                                   # Tabla extensa: manejo de saltos de página.


def test_generar_pdf_sin_registros_no_genera_archivo_vacio(tmp_path):
    reporte = _reporte(tmp_path)
    datos = reporte.generar_pdf([])
    assert datos.startswith(b"%PDF-")
    assert len(datos) > 0


# --- Exportación no altera la bitácora -------------------------------------------------

def test_exportar_no_modifica_ni_elimina_registros(tmp_path):
    reporte = _reporte(tmp_path)
    reporte._bitacora.registrar(TipoEvento.CONEXION, MAC_PC)
    antes = reporte.historial()
    reporte.generar_csv(antes)
    reporte.generar_pdf(antes, tipo=None)
    assert len(reporte.historial()) == len(antes)


def test_exportar_con_filtros_refleja_solo_los_eventos(tmp_path):
    reporte = _reporte(tmp_path)
    reporte._bitacora.registrar(TipoEvento.CONEXION, MAC_PC)
    reporte._bitacora.registrar(TipoEvento.BLOQUEO, MAC_PC, resultado=ResultadoEvento.EXITOSO)
    eventos = reporte.historial(tipos=[TipoEvento.BLOQUEO])
    filas = list(csv.reader(io.StringIO(reporte.generar_csv(eventos))))
    assert len(filas) == 2                                   # Cabecera + el único BLOQUEO.
    assert filas[1][1] == "Aislamiento"


# --- Controlador de reportes -----------------------------------------------------------

def test_controller_genera_pdf_crea_archivo(qapp, tmp_path, monkeypatch):
    reporte = _reporte(tmp_path)
    reporte._bitacora.registrar(TipoEvento.CONEXION, MAC_PC)
    vista = ReporteView()
    controlador = ReporteController(vista, reporte)
    monkeypatch.setattr(ReporteView, "elegir_destino", lambda self, sugerida, formato: sugerida)
    informados = []
    monkeypatch.setattr(ReporteView, "informar_generado", lambda self, ruta, n: informados.append((ruta, n)))
    controlador._generar()
    ruta = tmp_path / ("reporte_cybera_%s.pdf" % date.today().strftime("%Y-%m-%d"))
    assert ruta.exists()
    assert ruta.read_bytes().startswith(b"%PDF-")
    assert informados == [(ruta, 1)]


def test_controller_genera_csv_en_la_ruta_elegida_con_el_tipo_seleccionado(qapp, tmp_path, monkeypatch):
    from app.models.evento_bitacora import ResultadoEvento
    from presentation.views.reporte_view import FORMATO_CSV as CSV, OPCION_AISLAMIENTOS
    reporte = _reporte(tmp_path)
    reporte._bitacora.registrar(TipoEvento.CONEXION, MAC_PC)
    reporte._bitacora.registrar(TipoEvento.BLOQUEO, MAC_PC, resultado=ResultadoEvento.EXITOSO)
    vista = ReporteView()
    controlador = ReporteController(vista, reporte)
    destino = tmp_path / "elegido" / "mi_reporte.csv"
    monkeypatch.setattr(ReporteView, "elegir_destino", lambda self, sugerida, formato: destino)
    monkeypatch.setattr(ReporteView, "informar_generado", lambda self, ruta, n: None)
    vista.seleccionar_tipo(OPCION_AISLAMIENTOS)
    vista.seleccionar_formato(CSV)
    controlador._generar()
    filas = list(csv.reader(io.StringIO(destino.read_text(encoding="utf-8-sig"))))
    assert [f[1] for f in filas[1:]] == ["Aislamiento"]


def test_controller_no_guarda_si_el_usuario_cancela(qapp, tmp_path, monkeypatch):
    reporte = _reporte(tmp_path)
    reporte._bitacora.registrar(TipoEvento.CONEXION, MAC_PC)
    vista = ReporteView()
    controlador = ReporteController(vista, reporte)
    monkeypatch.setattr(ReporteView, "elegir_destino", lambda self, sugerida, formato: None)
    controlador._generar()
    assert list(tmp_path.glob("reporte_cybera_*")) == []
    assert vista.boton_generar.isEnabled()


def test_controller_informa_sin_registros_y_no_guarda(qapp, tmp_path):
    reporte = _reporte(tmp_path)                    # Historial vacío.
    vista = ReporteView()
    controlador = ReporteController(vista, reporte)
    controlador._generar()
    assert "No hay registros" in vista._mensaje.text()
    assert list(tmp_path.glob("reporte_cybera_*")) == []


def test_controller_muestra_error_si_falla_la_exportacion(qapp, tmp_path):
    class ReporteFalla:
        def historial(self, **kwargs):
            raise RuntimeError("fallo de lectura de la bitácora")

        def guardar_csv(self, eventos, hoy=None):
            raise RuntimeError("fallo de escritura")

        def guardar_pdf(self, eventos, **kwargs):
            raise RuntimeError("fallo de generación")

    reporte = _reporte(tmp_path)
    vista = ReporteView()
    controlador = ReporteController(vista, reporte)
    controlador._reporte = ReporteFalla()
    controlador._generar()
    assert vista._mensaje.property("error") == "true"


def test_controller_valida_rango_y_no_guarda(qapp, tmp_path):
    reporte = _reporte(tmp_path)
    vista = ReporteView()
    controlador = ReporteController(vista, reporte)
    from PySide6.QtCore import QDate
    vista.calendario_hasta.setDate(QDate.currentDate().addDays(-1))
    vista.calendario_desde.setDate(QDate.currentDate())
    controlador._generar()
    assert vista._mensaje.property("error") == "true"
    assert list(tmp_path.glob("reporte_cybera_*")) == []
