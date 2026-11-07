"""Pruebas del módulo de notificaciones por correo (detección de dispositivos nuevos).

Cubre: guardado y lectura segura de la configuración (la contraseña nunca vuelve a
la interfaz ni se escribe en notificaciones.json), validación, correo de prueba con
éxito y con fallo, agrupación (1 dispositivo → 1 correo con 1; 10 del mismo grupo →
1 correo con 10), no repetir alerta de un dispositivo ya conocido, dos grupos → dos
correos, un fallo SMTP no detiene el monitoreo, reintentos sin duplicados, y que la
app funcione sin configuración SMTP.

No se envían correos reales: el enviador está sustituido por un doble.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

import pytest

from app.models.dispositivo import EstadoDispositivo, PerfilDispositivo
from app.services.device_discovery_service import DeviceDiscoveryService
from app.services.monitoring_service import MonitoringService, TipoResultado
from app.services.network_interface_service import NetworkInterfaceService
from app.services.notificacion_service import (ConfiguracionCorreoError, NotificacionService,
                                               correo_valido)
from app.services.settings_service import SettingsService
from app.services.whitelist_service import WhitelistService
from dobles import HostnamesFalso, OuiFalso, ProveedorInterfacesFalso, SondaFalsa, interfaz
from infrastructure.correo.smtp_gmail import CorreoError, Mensaje
from infrastructure.persistence.notificaciones_repository import JsonNotificacionesRepository
from infrastructure.persistence.settings_repository import JsonSettingsRepository
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository
from infrastructure.secretos import CLAVE_SMTP, AlmacenEnMemoria

T0 = datetime(2026, 10, 20, 12, 0, 0)
REMITENTE = "vigilante@gmail.com"
APP_PASS = "abcd efgh ijkl mnop"


class EnviadorDoble:
    """Doble del enviador SMTP: registra los envíos y simula fallos opcionales."""

    def __init__(self, fallo: CorreoError | None = None) -> None:
        self.enviados: list[tuple[str, str, Mensaje]] = []
        self.fallo = fallo
        self.intentos = 0

    def enviar(self, remitente: str, contrasena: str, mensaje: Mensaje) -> None:
        self.intentos += 1
        if self.fallo is not None:
            raise self.fallo
        self.enviados.append((remitente, contrasena, mensaje))


def _servicio(tmp_path, enviador=None, almacen=None, asincrono=False, reloj=None):
    repo = JsonNotificacionesRepository(tmp_path / "notificaciones.json")
    return NotificacionService(repo, almacen or AlmacenEnMemoria(), enviador=enviador or EnviadorDoble(),
                               asincrono=asincrono, reloj=reloj or (lambda: T0))


def _perfil(mac, ip=None, hostname=None, fabricante=None):
    return PerfilDispositivo(mac=mac, ip=ip, primera_deteccion=T0, ultima_deteccion=T0,
                             hostname=hostname, fabricante=fabricante,
                             estado=EstadoDispositivo.DESCONOCIDO)


# --- Validación de correo ----------------------------------------------------------

@pytest.mark.parametrize("correo,ok", [
    ("usuario@gmail.com", True), ("a.b-c@sub.dominio.com", True),
    ("sinarroba", False), ("sin@dominio", False), ("con espacio@x.com", False), ("", False)])
def test_validacion_de_correo(correo, ok):
    assert correo_valido(correo) is ok


# --- Guardado y lectura segura -----------------------------------------------------

def test_guardar_config_persiste_remitente_y_guarda_pass_en_almacen(tmp_path):
    almacen = AlmacenEnMemoria()
    servicio = _servicio(tmp_path, almacen=almacen)
    estado = servicio.guardar_config(REMITENTE, APP_PASS)
    assert estado.configurado and estado.remitente == REMITENTE and estado.tiene_contrasena
    # El remitente se guarda; la contraseña NO está en el archivo.
    contenido = (tmp_path / "notificaciones.json").read_text(encoding="utf-8")
    assert REMITENTE in contenido
    assert APP_PASS not in contenido
    assert "password" not in contenido.lower() and "contrase" not in contenido.lower()
    assert json.loads(contenido).get("remitente") == REMITENTE
    # La contraseña vive en el almacén seguro.
    assert almacen.leer(CLAVE_SMTP) == APP_PASS


def test_estado_nunca_expone_la_contrasena(tmp_path):
    servicio = _servicio(tmp_path)
    servicio.guardar_config(REMITENTE, APP_PASS)
    estado = servicio.estado()
    assert not hasattr(estado, "contrasena") and not hasattr(estado, "password")
    assert APP_PASS not in repr(estado)
    assert estado.tiene_contrasena is True


def test_pass_vacia_no_sobrescribe_credencial_valida(tmp_path):
    almacen = AlmacenEnMemoria()
    servicio = _servicio(tmp_path, almacen=almacen)
    servicio.guardar_config(REMITENTE, APP_PASS)
    # Edita solo el correo, deja la contraseña vacía: debe conservarse.
    servicio.guardar_config("otro@gmail.com", "")
    assert almacen.leer(CLAVE_SMTP) == APP_PASS
    assert servicio.estado().remitente == "otro@gmail.com"


def test_pass_obligatoria_la_primera_vez(tmp_path):
    servicio = _servicio(tmp_path)
    with pytest.raises(ConfiguracionCorreoError):
        servicio.guardar_config(REMITENTE, "")
    assert not servicio.esta_configurado()


def test_correo_invalido_se_rechaza(tmp_path):
    servicio = _servicio(tmp_path)
    with pytest.raises(ConfiguracionCorreoError):
        servicio.guardar_config("no-es-correo", APP_PASS)


# --- Correo de prueba --------------------------------------------------------------

def test_prueba_envia_al_remitente(tmp_path):
    enviador = EnviadorDoble()
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.guardar_config(REMITENTE, APP_PASS)
    servicio.enviar_prueba()
    assert len(enviador.enviados) == 1
    remitente, contrasena, mensaje = enviador.enviados[0]
    assert remitente == REMITENTE and contrasena == APP_PASS
    assert mensaje.destinatario == REMITENTE
    assert "prueba" in mensaje.asunto.lower()


def test_prueba_propaga_el_fallo_real(tmp_path):
    enviador = EnviadorDoble(fallo=CorreoError("Gmail rechazó las credenciales.", reintentable=False))
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.guardar_config(REMITENTE, APP_PASS)
    with pytest.raises(CorreoError):
        servicio.enviar_prueba()


def test_prueba_sin_configuracion_falla(tmp_path):
    servicio = _servicio(tmp_path)
    with pytest.raises(ConfiguracionCorreoError):
        servicio.enviar_prueba()


# --- Agrupación de dispositivos nuevos ---------------------------------------------

def test_un_dispositivo_produce_un_correo_con_uno(tmp_path):
    enviador = EnviadorDoble()
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.guardar_config(REMITENTE, APP_PASS)
    servicio.notificar_nuevos([_perfil("AA:BB:CC:00:00:01", ip="10.0.0.2", hostname="PC-1")])
    assert len(enviador.enviados) == 1
    mensaje = enviador.enviados[0][2]
    assert "un nuevo dispositivo" in mensaje.texto
    assert mensaje.texto.count("Dispositivo 1:") == 1
    assert "Dispositivo 2:" not in mensaje.texto


def test_diez_dispositivos_del_mismo_grupo_producen_un_solo_correo(tmp_path):
    enviador = EnviadorDoble()
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.guardar_config(REMITENTE, APP_PASS)
    perfiles = [_perfil(f"AA:BB:CC:00:00:{i:02X}", ip=f"10.0.0.{i}") for i in range(1, 11)]
    servicio.notificar_nuevos(perfiles)
    assert len(enviador.enviados) == 1                 # UN correo, no diez.
    mensaje = enviador.enviados[0][2]
    assert "10 nuevos dispositivos" in mensaje.texto
    for i in range(1, 11):
        assert f"Dispositivo {i}:" in mensaje.texto
    assert mensaje.html and "AA:BB:CC:00:00:0A" in mensaje.html


def test_sin_dispositivos_no_envia(tmp_path):
    enviador = EnviadorDoble()
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.guardar_config(REMITENTE, APP_PASS)
    servicio.notificar_nuevos([])
    assert enviador.enviados == []


def test_sin_configuracion_no_envia_y_no_falla(tmp_path):
    enviador = EnviadorDoble()
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.notificar_nuevos([_perfil("AA:BB:CC:00:00:01")])     # No configurado.
    assert enviador.enviados == []


def test_dato_no_disponible_se_indica(tmp_path):
    enviador = EnviadorDoble()
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.guardar_config(REMITENTE, APP_PASS)
    servicio.notificar_nuevos([_perfil("AA:BB:CC:00:00:09")])     # sin ip, hostname, fabricante
    mensaje = enviador.enviados[0][2]
    assert "No disponible" in mensaje.texto


# --- Fallo SMTP y reintentos -------------------------------------------------------

def test_fallo_smtp_no_propaga_en_notificacion(tmp_path):
    enviador = EnviadorDoble(fallo=CorreoError("Gmail no aceptó el mensaje.", reintentable=True))
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.guardar_config(REMITENTE, APP_PASS)
    # No debe lanzar: notificar_nuevos (síncrono) traga el error tras reintentar.
    servicio.notificar_nuevos([_perfil("AA:BB:CC:00:00:01")])
    assert enviador.enviados == []                     # Ninguno se completó.
    assert enviador.intentos >= 1


def test_fallo_no_reintentable_no_reintenta(tmp_path):
    enviador = EnviadorDoble(fallo=CorreoError("Credenciales inválidas.", reintentable=False))
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.guardar_config(REMITENTE, APP_PASS)
    servicio.notificar_nuevos([_perfil("AA:BB:CC:00:00:01")])
    assert enviador.intentos == 1                      # No se reintenta un fallo de credenciales.


def test_envio_exitoso_no_duplica(tmp_path):
    enviador = EnviadorDoble()
    servicio = _servicio(tmp_path, enviador=enviador)
    servicio.guardar_config(REMITENTE, APP_PASS)
    servicio.notificar_nuevos([_perfil("AA:BB:CC:00:00:01")])
    assert enviador.intentos == 1 and len(enviador.enviados) == 1


# --- Integración con el detector real (MonitoringService) --------------------------

def _entorno_monitoreo(tmp_path, enviador, respuestas):
    proveedor = ProveedorInterfacesFalso([interfaz()])
    sonda = SondaFalsa(respuestas)
    configuracion = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
    lb = WhitelistService(JsonWhitelistRepository(tmp_path / "lista_blanca.json"))
    notif = _servicio(tmp_path, enviador=enviador)
    notif.guardar_config(REMITENTE, APP_PASS)
    descubrimiento = DeviceDiscoveryService(sonda, OuiFalso({}), HostnamesFalso(),
                                            nombre_equipo="ESTE-PC", tiempo_maximo_hostname=0.2)
    servicio = MonitoringService(configuracion, NetworkInterfaceService(proveedor),
                                 descubrimiento, lb, notificaciones=notif)
    configuracion.seleccionar_interfaz(interfaz())
    configuracion.activar_monitoreo()
    return servicio


def test_monitoreo_agrupa_nuevos_en_un_correo_y_no_repite(tmp_path):
    enviador = EnviadorDoble()
    # Dos dispositivos aparecen en el mismo ciclo → un solo correo con los dos.
    servicio = _entorno_monitoreo(tmp_path, enviador,
                                  {"10.0.0.14": "50:9A:4C:4C:78:B2", "10.0.0.15": "50:9A:4C:4C:78:C3"})
    r1 = servicio.ejecutar_ciclo(threading.Event())
    assert r1.tipo is TipoResultado.ACTUALIZADO
    assert len(enviador.enviados) == 1
    assert "2 nuevos dispositivos" in enviador.enviados[0][2].texto
    # Segundo ciclo: los mismos dispositivos ya conocidos → no se repite el correo.
    servicio.ejecutar_ciclo(threading.Event())
    assert len(enviador.enviados) == 1


def test_monitoreo_dos_grupos_distintos_producen_dos_correos(tmp_path):
    enviador = EnviadorDoble()
    sonda = SondaFalsa({"10.0.0.14": "50:9A:4C:4C:78:B2"})
    proveedor = ProveedorInterfacesFalso([interfaz()])
    configuracion = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
    lb = WhitelistService(JsonWhitelistRepository(tmp_path / "lista_blanca.json"))
    notif = _servicio(tmp_path, enviador=enviador)
    notif.guardar_config(REMITENTE, APP_PASS)
    descubrimiento = DeviceDiscoveryService(sonda, OuiFalso({}), HostnamesFalso(),
                                            nombre_equipo="ESTE-PC", tiempo_maximo_hostname=0.2)
    servicio = MonitoringService(configuracion, NetworkInterfaceService(proveedor),
                                 descubrimiento, lb, notificaciones=notif)
    configuracion.seleccionar_interfaz(interfaz())
    configuracion.activar_monitoreo()
    servicio.ejecutar_ciclo(threading.Event())
    assert len(enviador.enviados) == 1
    # Aparece un segundo dispositivo nuevo en otro ciclo → segundo correo.
    sonda.respuestas["10.0.0.20"] = "50:9A:4C:4C:78:D4"
    servicio.ejecutar_ciclo(threading.Event())
    assert len(enviador.enviados) == 2
    assert "un nuevo dispositivo" in enviador.enviados[1][2].texto


def test_monitoreo_continua_aunque_falle_el_correo(tmp_path):
    enviador = EnviadorDoble(fallo=CorreoError("Gmail no aceptó el mensaje.", reintentable=False))
    servicio = _entorno_monitoreo(tmp_path, enviador, {"10.0.0.14": "50:9A:4C:4C:78:B2"})
    resultado = servicio.ejecutar_ciclo(threading.Event())
    assert resultado.tipo is TipoResultado.ACTUALIZADO     # El ciclo termina bien.
    assert resultado.dispositivos                           # Devuelve los dispositivos vistos.
    assert enviador.enviados == []                          # El correo falló, pero no rompió nada.


def test_monitoreo_sin_notificador_funciona(tmp_path):
    proveedor = ProveedorInterfacesFalso([interfaz()])
    sonda = SondaFalsa({"10.0.0.14": "50:9A:4C:4C:78:B2"})
    configuracion = SettingsService(JsonSettingsRepository(tmp_path / "configuracion.json"))
    lb = WhitelistService(JsonWhitelistRepository(tmp_path / "lista_blanca.json"))
    descubrimiento = DeviceDiscoveryService(sonda, OuiFalso({}), HostnamesFalso(),
                                            nombre_equipo="ESTE-PC", tiempo_maximo_hostname=0.2)
    servicio = MonitoringService(configuracion, NetworkInterfaceService(proveedor),
                                 descubrimiento, lb)       # notificaciones=None
    configuracion.seleccionar_interfaz(interfaz())
    configuracion.activar_monitoreo()
    resultado = servicio.ejecutar_ciclo(threading.Event())
    assert resultado.tipo is TipoResultado.ACTUALIZADO


# --- Asíncrono: el envío ocurre en el hilo de trabajo sin bloquear -----------------

def test_envio_asincrono_no_bloquea_y_entrega(tmp_path):
    enviador = EnviadorDoble()
    servicio = _servicio(tmp_path, enviador=enviador, asincrono=True)
    servicio.guardar_config(REMITENTE, APP_PASS)
    servicio.notificar_nuevos([_perfil("AA:BB:CC:00:00:01")])
    # El hilo de trabajo procesa la cola; esperamos a que termine sin bloquear el envío.
    servicio._cola.join()
    servicio.detener()
    assert len(enviador.enviados) == 1


# --- Vista y controlador (estados de carga, éxito y error) -------------------------

def _vista_y_controlador(tmp_path, enviador=None):
    from app.controllers.notificacion_controller import NotificacionController
    from presentation.views.settings_view import SettingsView
    servicio = _servicio(tmp_path, enviador=enviador or EnviadorDoble())
    vista = SettingsView()
    controlador = NotificacionController(vista, servicio)
    return vista, controlador, servicio


def _esperar(pool, condicion, limite=5.0):
    import time
    from PySide6.QtWidgets import QApplication
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        QApplication.processEvents()
        if condicion():
            return True
        time.sleep(0.02)
    QApplication.processEvents()
    return condicion()


def test_vista_arranca_como_no_configurado(qapp, tmp_path):
    vista, _c, _s = _vista_y_controlador(tmp_path)
    assert vista.estado_correo.property("tono") == "no_configurado"


def test_controlador_guarda_y_muestra_configurado(qapp, tmp_path):
    vista, controlador, servicio = _vista_y_controlador(tmp_path)
    vista.correo_remitente.setText(REMITENTE)
    vista.correo_contrasena.setText(APP_PASS)
    vista._guardar_correo()
    assert _esperar(controlador._pool, lambda: vista.estado_correo.property("tono") == "configurado")
    assert servicio.esta_configurado()
    assert vista.correo_contrasena.text() == ""        # La contraseña se limpia del campo.


def test_controlador_valida_correo_vacio_sin_lanzar_tarea(qapp, tmp_path):
    vista, controlador, servicio = _vista_y_controlador(tmp_path)
    vista.correo_remitente.setText("")
    vista._guardar_correo()
    assert vista.estado_correo.property("tono") == "error"
    assert not servicio.esta_configurado()


def test_controlador_prueba_con_fallo_muestra_error(qapp, tmp_path):
    enviador = EnviadorDoble(fallo=CorreoError("Gmail rechazó las credenciales.", reintentable=False))
    vista, controlador, _s = _vista_y_controlador(tmp_path, enviador=enviador)
    vista.correo_remitente.setText(REMITENTE)
    vista.correo_contrasena.setText(APP_PASS)
    vista._probar_correo()
    assert _esperar(controlador._pool, lambda: vista.estado_correo.property("tono") == "error")
    assert "credenciales" in vista.aviso_correo.text().lower()


def test_mostrar_contrasena_cambia_echo(qapp, tmp_path):
    from PySide6.QtWidgets import QLineEdit
    vista, _c, _s = _vista_y_controlador(tmp_path)
    assert vista.correo_contrasena.echoMode() == QLineEdit.EchoMode.Password
    vista.boton_ver_pass.setChecked(True)
    assert vista.correo_contrasena.echoMode() == QLineEdit.EchoMode.Normal
    assert vista.boton_ver_pass.text() == "Ocultar"
