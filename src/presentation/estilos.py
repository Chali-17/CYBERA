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
QFrame#panel QLabel#pastillaConfiable {{
    background: {VERDE}; color: white; font-size: 13px; font-weight: 700;
    border-radius: 6px; padding: 7px 18px;
}}
QPushButton#botonEditar {{
    background: {GRIS_BOTON}; color: {TEXTO}; font-size: 13px; font-weight: 700;
    border: none; border-radius: 6px; padding: 8px 20px;
}}
QPushButton#botonEditar:hover {{ background: #DCE4EF; }}
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
QLabel#estadoCorreo {{ font-size: 13px; font-weight: 700; padding: 6px 14px; border-radius: 6px; }}
QLabel#estadoCorreo[tono="configurado"] {{ color: {VERDE}; background: #DCFCE7; }}
QLabel#estadoCorreo[tono="no_configurado"] {{ color: {TEXTO_SUAVE}; background: {GRIS_BOTON}; }}
QLabel#estadoCorreo[tono="error"] {{ color: {ROJO}; background: #FEE2E2; }}
QLabel#estadoCorreo[tono="cargando"] {{ color: {AMBAR}; background: #FEF3C7; }}
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
QPushButton#botonRojoSuave {{
    background: white; color: {ROJO}; border: 1px solid {ROJO}; min-width: 120px;
}}
QPushButton#botonRojoSuave:hover:enabled {{ background: #FEF2F2; }}
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

/* Pantalla Aislamiento (Mockup 06): una tarjeta por dispositivo bajo contención. */
QScrollArea#listaAislamiento, QWidget#contenedorAislamiento {{ background: white; border: none; }}
QFrame#filaAislamiento {{
    background: {FONDO}; border: 1px solid {BORDE}; border-radius: 14px;
}}
QFrame#filaAislamiento QLabel {{ color: {TEXTO_CELDA}; font-size: 13px; background: transparent; }}
QFrame#filaAislamiento QLabel#nombreFila {{ color: {TEXTO}; font-size: 15px; font-weight: 700; }}
QFrame#filaAislamiento QLabel#fechaFila {{ color: {TEXTO_SUAVE}; }}
QLabel#insigniaAislamiento {{
    border-radius: 6px; font-size: 14px; font-weight: 700; min-height: 40px;
    min-width: 120px; padding: 0 16px;
}}
QLabel#insigniaAislamiento[tono="rojo"] {{ background: {ROJO}; color: white; }}
QLabel#insigniaAislamiento[tono="ambar"] {{ background: #FEF3C7; color: {AMBAR}; }}
QLabel#insigniaAislamiento[tono="gris"] {{ background: {GRIS_BOTON}; color: {TEXTO_SUAVE}; }}
QPushButton#botonAzul:disabled {{ background: #CBD5E1; color: white; }}
QPushButton#opcion {{
    background: {GRIS_BOTON}; color: {TEXTO}; border: none; border-radius: 6px;
    font-size: 13px; font-weight: 700; min-height: 40px; padding: 0 18px;
}}
QPushButton#opcion:hover {{ background: #DCE4EF; }}
QPushButton#opcion:checked {{ background: {AZUL}; color: white; }}
QPushButton#opcion:disabled {{ background: #CBD5E1; color: white; }}

/* Resumen (Mockup 02): tarjetas de indicadores y actividad reciente. */
QFrame#tarjetaResumen {{ background: white; border: 1px solid {BORDE}; border-radius: 22px; }}
QFrame#tarjetaResumen QLabel {{ background: transparent; border: none; }}
QLabel#tituloTarjeta {{ color: {TEXTO_SUAVE}; font-size: 14px; font-weight: 600; }}
QLabel#valorTarjeta {{ color: {TEXTO}; font-size: 34px; font-weight: 700; }}
QLabel#notaTarjeta {{ color: {TEXTO_SUAVE}; font-size: 11px; }}
QScrollArea#listaActividad, QWidget#contenedorActividad, QWidget#filaActividad {{
    background: white; border: none;
}}
QLabel#tituloActividad {{ color: {TEXTO}; font-size: 14px; font-weight: 700; }}
QLabel#detalleActividad {{ color: {TEXTO_SUAVE}; font-size: 13px; }}
QLabel#insigniaActividad {{
    border-radius: 6px; font-size: 14px; font-weight: 700; min-height: 40px;
    min-width: 150px; max-width: 150px; padding: 0 8px;
}}
QLabel#insigniaActividad[tono="naranja"] {{ background: #D97706; color: white; }}
QLabel#insigniaActividad[tono="verde"] {{ background: {VERDE}; color: white; }}
QLabel#insigniaActividad[tono="rojo"] {{ background: {ROJO}; color: white; }}
QLabel#insigniaActividad[tono="azul"] {{ background: {AZUL}; color: white; }}
QLabel#insigniaActividad[tono="ambar"] {{ background: #FEF3C7; color: {AMBAR}; }}
QLabel#insigniaActividad[tono="gris"] {{ background: {GRIS_BOTON}; color: {TEXTO_SUAVE}; }}

/* Bitácora (Mockup 07) y Reportes (Mockup 08): campos de fecha y filtros. */
QDateEdit#campo {{
    background: {FONDO}; border: 1px solid {BORDE_CAMPO}; border-radius: 8px;
    padding: 0 16px; min-height: 52px; font-size: 14px; color: {TEXTO};
}}
QDateEdit#campo::drop-down {{ border: none; width: 34px; }}
QPushButton#campoBoton {{
    background: {FONDO}; border: 1px solid {BORDE_CAMPO}; border-radius: 8px;
    padding: 0 16px; min-height: 46px; font-size: 13px; color: {TEXTO_SUAVE}; text-align: left;
}}
QPushButton#campoBoton[activo="true"] {{ color: {TEXTO}; border-color: {AZUL}; }}
QPushButton#campoBoton:hover {{ border-color: #B8C4D6; }}
QPushButton#botonVaciar {{
    background: {GRIS_BOTON}; color: {TEXTO}; border: none; border-radius: 6px;
    font-size: 14px; font-weight: 700; min-height: 54px; min-width: 112px; padding: 0 12px;
}}
QPushButton#botonVaciar:hover {{ background: #FDE2E2; color: {ROJO}; }}
QFrame#popupRango {{ background: white; border: 1px solid {BORDE}; border-radius: 12px; }}
QFrame#popupRango QLabel {{ background: transparent; }}
QFrame#popupRango QPushButton#botonAzul, QFrame#popupRango QPushButton#botonNeutro {{
    min-width: 110px; min-height: 38px;
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {GRIS_BOTON}; }}
QCalendarWidget QToolButton {{ color: {TEXTO}; font-weight: 600; background: transparent; }}
QCalendarWidget QSpinBox {{ background: white; color: {TEXTO}; }}
QCalendarWidget QMenu {{ background: white; color: {TEXTO}; }}
"""
