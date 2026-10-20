"""Paleta y hoja de estilos tomadas de los mockups 03 y 09."""

AZUL_OSCURO = "#14213D"     # Barra lateral
AZUL = "#2563EB"            # Opción activa y botones primarios
VERDE = "#16A34A"           # Indicador «MONITOREO ACTIVO» y «Guardar»
FONDO = "#F4F7FB"
TEXTO = "#1F2937"
TEXTO_CELDA = "#334155"
TEXTO_SUAVE = "#64748B"
BORDE = "#DCE3EC"
BORDE_CAMPO = "#E0E7EF"
GRIS_BOTON = "#E8EEF6"
AMBAR = "#B45309"
ROJO = "#DC2626"            # Acción de defensa activa (Aislar)

ANCHO_BARRA_LATERAL = 250

HOJA_ESTILOS = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; }}
QWidget#raiz, QWidget#pagina, QWidget#contenidoDesplazable {{ background: {FONDO}; }}
QScrollArea {{ background: transparent; border: none; }}

QFrame#barraLateral {{ background: {AZUL_OSCURO}; }}
QLabel#marca {{ color: white; font-size: 30px; font-weight: 700; }}
QLabel#marcaSub {{ color: #CBD5E1; font-size: 13px; }}
QPushButton#nav, QLabel#nav {{
    color: #E2E8F0; font-size: 15px; text-align: left; border: none;
    border-radius: 8px; background: transparent; padding-left: 22px; min-height: 44px;
}}
QPushButton#nav {{ padding-left: 25px; }}
QPushButton#nav:hover {{ background: rgba(255, 255, 255, 0.07); }}
QPushButton#nav:checked {{ background: {AZUL}; color: white; font-weight: 700; }}

QLabel#tituloPagina {{ color: {TEXTO}; font-size: 30px; font-weight: 700; }}
QLabel#subtituloPagina {{ color: {TEXTO_SUAVE}; font-size: 15px; }}
QLabel#pie {{ color: {TEXTO_SUAVE}; font-size: 12px; }}

QLabel#indicador {{ border-radius: 7px; padding: 11px 30px; font-size: 13px; font-weight: 700; }}
QLabel#indicador[estado="ACTIVO"] {{ background: {VERDE}; color: white; }}
QLabel#indicador[estado="INACTIVO"] {{ background: #E2E8F0; color: #475569; }}
QLabel#indicador[estado="ERROR"] {{ background: #D97706; color: white; }}

QFrame#panel {{ background: white; border: 1px solid {BORDE}; border-radius: 44px; }}
QFrame#panel QLabel {{ background: transparent; border: none; }}
QLabel#tituloPanel {{ color: {TEXTO}; font-size: 21px; font-weight: 700; }}

QTableWidget#tablaDispositivos {{
    background: white; border: none; color: {TEXTO_CELDA}; font-size: 13px;
    gridline-color: transparent; outline: 0;
}}
QTableWidget#tablaDispositivos::item {{ border-bottom: 1px solid #EEF2F7; padding-left: 14px; }}
QTableWidget#tablaDispositivos::item:hover {{ background: transparent; }}
QTableWidget#tablaDispositivos QHeaderView::section {{
    background: white; color: {TEXTO_SUAVE}; font-size: 12px; font-weight: 600;
    border: none; border-bottom: 1px solid #E5EAF1; padding-left: 14px; min-height: 52px;
}}
QWidget#celdaAccion {{ background: transparent; border-bottom: 1px solid #EEF2F7; }}
QPushButton#accionTabla {{
    background: transparent; border: none; color: {TEXTO}; font-size: 13px;
    text-align: left; padding: 0;
}}
QPushButton#accionTabla:hover {{ color: {AZUL}; text-decoration: underline; }}
QLabel#accionInactiva {{ color: {TEXTO_SUAVE}; font-size: 13px; }}
QLabel#mensajeTabla {{ color: {TEXTO_SUAVE}; font-size: 14px; }}
QLabel#mensajeTabla[error="true"] {{ color: {AMBAR}; }}

QLabel#etiquetaCampo {{ color: {TEXTO}; font-size: 13px; font-weight: 700; }}
QLabel#ayuda {{ color: {TEXTO_SUAVE}; font-size: 12px; }}
QLabel#estadoMonitoreo {{ color: {TEXTO_CELDA}; font-size: 13px; }}
QLabel#aviso {{ font-size: 13px; font-weight: 600; }}
QLabel#aviso[exito="true"] {{ color: {VERDE}; }}
QLabel#aviso[exito="false"] {{ color: {AMBAR}; }}
QComboBox#campo, QLineEdit#campo {{
    background: {FONDO}; border: 1px solid {BORDE_CAMPO}; border-radius: 8px;
    padding: 0 16px; min-height: 46px; font-size: 13px; color: {TEXTO};
}}
QComboBox#campo {{ combobox-popup: 0; }}
QComboBox#campo::drop-down {{ border: none; width: 34px; }}
QComboBox#campo QAbstractItemView, QListView#listaInterfaces {{
    background: white; border: 1px solid {BORDE}; border-radius: 8px; padding: 4px;
    outline: 0; color: {TEXTO}; font-size: 13px;
}}
QListView#listaInterfaces::item {{
    min-height: 38px; padding: 0 12px; border-radius: 6px; color: {TEXTO};
}}
QListView#listaInterfaces::item:selected, QListView#listaInterfaces::item:hover {{
    background: {GRIS_BOTON}; color: {TEXTO};
}}
QLineEdit#campo:disabled {{ color: {TEXTO_SUAVE}; }}

QPushButton#canalActivo, QPushButton#canal, QPushButton#botonAzul,
QPushButton#botonVerde, QPushButton#botonNeutro, QPushButton#botonRojo {{
    border: none; border-radius: 6px; font-size: 14px; font-weight: 700; min-height: 44px;
    padding: 0 22px;
}}
QPushButton#canalActivo {{ background: {AZUL}; color: white; min-width: 120px; }}
QPushButton#canal {{ background: {GRIS_BOTON}; color: {TEXTO}; min-width: 120px; }}
QPushButton#botonAzul {{ background: {AZUL}; color: white; min-width: 150px; }}
QPushButton#botonVerde {{ background: {VERDE}; color: white; min-width: 150px; }}
QPushButton#botonRojo {{ background: {ROJO}; color: white; min-width: 120px; }}
QPushButton#botonRojo:hover:enabled {{ background: #B91C1C; }}
QPushButton#botonNeutro {{ background: {GRIS_BOTON}; color: {TEXTO}; min-width: 150px; }}
QPushButton#botonAzul:hover:enabled {{ background: #1D4ED8; }}
QPushButton#botonVerde:hover:enabled {{ background: #15803D; }}
QPushButton#botonNeutro:hover:enabled {{ background: #DCE4EF; }}
QPushButton#botonVerde:disabled[funcional="true"], QPushButton#botonNeutro:disabled[funcional="true"] {{
    background: #CBD5E1; color: white;
}}

QDialog#dialogoRevision {{ background: white; }}
QDialog#dialogoRevision QLabel {{ color: {TEXTO_CELDA}; font-size: 13px; }}
QDialog#dialogoRevision QLabel#tituloDialogo {{ color: {TEXTO}; font-size: 18px; font-weight: 700; }}
QDialog#dialogoRevision QLabel#claveDato {{ color: {TEXTO_SUAVE}; font-weight: 600; }}
QDialog#dialogoRevision QLabel#nota {{ color: {AMBAR}; font-size: 12px; }}
"""
