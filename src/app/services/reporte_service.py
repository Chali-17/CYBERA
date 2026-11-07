"""ReporteService: consulta y exportación del historial de la bitácora (módulo Reportes).

- **Consulta**: delega en ``BitacoraService`` (fuente de datos real de la bitácora).
  No se accede a la persistencia directamente desde la exportación.
- **Exportación CSV**: genera el contenido con cabeceras claras, separador y saltos de
  línea correctos (RFC 4180), codificación UTF-8 con BOM (compatible con Excel) y protección
  contra fórmulas de hoja de cálculo con valores no confiables.
- **Exportación PDF**: genera un PDF válido con reportlab (título, fecha de generación,
  periodo/filtros consultados y tabla con encabezados repetidos y numeración de página).

El módulo solo consulta y exporta: la bitácora sigue siendo la responsable de registrar y
conservar los eventos. Ninguna exportación modifica ni elimina registros.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.evento_bitacora import EventoBitacora, TipoEvento, etiqueta_resultado, etiqueta_tipo
from app.services.bitacora_service import BitacoraService

CABECERAS = ["Fecha y hora", "Evento", "Dispositivo", "IP", "Dirección MAC", "Resultado"]
EXTENSION_CSV = "csv"
EXTENSION_PDF = "pdf"
FORMATO_CSV = "csv"
FORMATO_PDF = "pdf"
TITULO_PDF = "Reporte de actividad de CYBERA"
INFO_EXPORTACION = "El archivo incluirá fecha, evento, nodo, IP, MAC y resultado."

_AZUL = colors.HexColor("#2563EB")
_AZUL_OSCURO = colors.HexColor("#14213D")
_TEXTO = colors.HexColor("#1F2937")
_TEXTO_SUAVE = colors.HexColor("#64748B")
_BORDE = colors.HexColor("#E5EAF1")
_FONDO_ALTERNO = colors.HexColor("#F4F7FB")
_ANCHOS_PDF = [42 * mm, 34 * mm, 72 * mm, 32 * mm, 42 * mm, 30 * mm]   # 252 mm útiles.


def _pie_de_pagina(canvas, doc) -> None:
    ancho, _ = doc.pagesize
    canvas.saveState()
    canvas.setStrokeColor(_BORDE)
    canvas.line(doc.leftMargin, 13 * mm, ancho - doc.rightMargin, 13 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(_TEXTO_SUAVE)
    canvas.drawString(doc.leftMargin, 9 * mm, "CYBERA • Control y aislamiento — Reporte de bitácora")
    canvas.drawRightString(ancho - doc.rightMargin, 9 * mm, f"Página {canvas.getPageNumber()}")
    canvas.restoreState()


class ReporteService:
    """Consulta el historial de la bitácora y genera reportes en CSV y PDF."""

    def __init__(self, bitacora: BitacoraService, directorio: Path) -> None:
        self._bitacora = bitacora
        self._directorio = Path(directorio)
        self._directorio.mkdir(parents=True, exist_ok=True)

    # --- Consulta -----------------------------------------------------------------

    def historial(self, tipo: TipoEvento | None = None, desde: datetime | None = None,
                  hasta: datetime | None = None, mac: str | None = None,
                  tipos: Sequence[TipoEvento] | None = None) -> list[EventoBitacora]:
        """Devuelve los eventos que cumplen el filtro, del más reciente al más antiguo."""
        return self._bitacora.historial(tipo=tipo, desde=desde, hasta=hasta, mac=mac, tipos=tipos)

    # --- Exportación CSV -----------------------------------------------------------

    def generar_csv(self, eventos: Sequence[EventoBitacora]) -> str:
        """Devuelve el contenido CSV (UTF-8 con BOM, CRLF y escapes RFC 4180)."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(CABECERAS)
        for evento in eventos:
            writer.writerow(self._fila(evento))
        return buffer.getvalue()

    def guardar_csv(self, eventos: Sequence[EventoBitacora], hoy: date | None = None,
                    ruta: Path | None = None) -> Path:
        """Guarda el reporte CSV en ``ruta`` (o en la carpeta de reportes con nombre descriptivo)."""
        ruta = Path(ruta) if ruta is not None else self.ruta_reporte(EXTENSION_CSV, hoy)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
            archivo.write(self.generar_csv(eventos))
        return ruta

    # --- Exportación PDF ------------------------------------------------------------

    def generar_pdf(self, eventos: Sequence[EventoBitacora], *, titulo: str = TITULO_PDF,
                    desde: datetime | None = None, hasta: datetime | None = None,
                    tipo: TipoEvento | Sequence[TipoEvento] | None = None) -> bytes:
        """Devuelve el contenido del PDF (A4 horizontal): título, filtros y tabla de eventos."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), title=titulo, author="CYBERA",
                                leftMargin=22 * mm, rightMargin=22 * mm,
                                topMargin=18 * mm, bottomMargin=20 * mm)
        base = getSampleStyleSheet()
        estilo_titulo = ParagraphStyle("titulo", parent=base["Title"], alignment=0, fontSize=20,
                                       leading=24, textColor=_AZUL_OSCURO, spaceAfter=4)
        estilo_dato = ParagraphStyle("dato", parent=base["Normal"], fontSize=9.5, leading=13,
                                     textColor=_TEXTO_SUAVE)

        story = [Paragraph(escape(titulo), estilo_titulo),
                 Paragraph("Historial de seguridad exportado desde la bitácora", estilo_dato),
                 Spacer(1, 10)]
        for clave, valor in self._resumen_filtros(eventos, desde, hasta, tipo):
            story.append(Paragraph(f"<b>{clave}:</b> {escape(valor)}", estilo_dato))
        story.append(Spacer(1, 14))
        if not eventos:
            story.append(Paragraph("No hay registros para los filtros seleccionados.", estilo_dato))
        else:
            story.append(self._tabla_pdf(eventos, base))
        doc.build(story, onFirstPage=_pie_de_pagina, onLaterPages=_pie_de_pagina)
        return buffer.getvalue()

    def guardar_pdf(self, eventos: Sequence[EventoBitacora], *, titulo: str = TITULO_PDF,
                    desde: datetime | None = None, hasta: datetime | None = None,
                    tipo: TipoEvento | Sequence[TipoEvento] | None = None,
                    hoy: date | None = None, ruta: Path | None = None) -> Path:
        """Guarda el reporte PDF en ``ruta`` (o en la carpeta de reportes con nombre descriptivo)."""
        ruta = Path(ruta) if ruta is not None else self.ruta_reporte(EXTENSION_PDF, hoy)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(self.generar_pdf(eventos, titulo=titulo, desde=desde, hasta=hasta, tipo=tipo))
        return ruta

    # --- Rutas -----------------------------------------------------------------------

    def ruta_reporte(self, extension: str, hoy: date | None = None) -> Path:
        sufijo = extension if extension.startswith(".") else "." + extension
        fecha = hoy or datetime.now().date()
        return self._directorio / ("reporte_cybera_%s%s" % (fecha.strftime("%Y-%m-%d"), sufijo))

    # --- Auxiliares -----------------------------------------------------------------

    @staticmethod
    def _valores(evento: EventoBitacora) -> list[str | None]:
        return [
            evento.fecha_hora.strftime("%d/%m/%Y %H:%M:%S"),
            etiqueta_tipo(evento.tipo),
            evento.nombre_dispositivo or evento.mac_dispositivo,
            evento.ip_dispositivo,
            evento.mac_dispositivo,
            etiqueta_resultado(evento.resultado),
        ]

    def _fila(self, evento: EventoBitacora) -> list[str]:
        return [self._celda(valor) for valor in self._valores(evento)]

    @staticmethod
    def _celda(valor) -> str:
        """Normaliza el valor a texto y evita que se interprete como fórmula de hoja de cálculo."""
        texto = "" if valor is None else str(valor)
        if texto[:1] in ("=", "+", "-", "@"):
            texto = "'" + texto
        return texto

    @staticmethod
    def _resumen_filtros(eventos, desde, hasta, tipo) -> list[tuple[str, str]]:
        if tipo is None:
            tipos = "Todos"
        else:
            valores = list(tipo) if isinstance(tipo, (list, tuple, set)) else [tipo]
            tipos = ", ".join(etiqueta_tipo(v) for v in valores)
        if desde is not None and hasta is not None:
            periodo = f"{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
        elif desde is not None:
            periodo = f"desde el {desde:%d/%m/%Y}"
        elif hasta is not None:
            periodo = f"hasta el {hasta:%d/%m/%Y}"
        else:
            periodo = "Todo el historial"
        return [("Periodo", periodo), ("Tipo de eventos", tipos),
                ("Total de eventos", str(len(eventos))),
                ("Generado", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))]

    def _tabla_pdf(self, eventos: Sequence[EventoBitacora], estilos) -> Table:
        celda = ParagraphStyle("celda", parent=estilos["Normal"], fontSize=8.5, leading=11,
                               textColor=_TEXTO)
        cabecera = ParagraphStyle("cabecera", parent=celda, fontName="Helvetica-Bold",
                                  textColor=colors.white)
        filas = [[Paragraph(escape(c), cabecera) for c in CABECERAS]]
        for evento in eventos:
            filas.append([Paragraph(escape(v or "No disponible"), celda) for v in self._valores(evento)])
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), _AZUL),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, _BORDE),
        ]
        estilo += [("BACKGROUND", (0, i), (-1, i), _FONDO_ALTERNO) for i in range(2, len(filas), 2)]
        return Table(filas, colWidths=_ANCHOS_PDF, repeatRows=1, style=TableStyle(estilo))
