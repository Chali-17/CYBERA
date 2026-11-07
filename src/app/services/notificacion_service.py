"""NotificacionService: alertas por correo cuando se detectan dispositivos nuevos.

Responsabilidades:
- Guardar y leer la configuración SMTP de forma segura. El correo remitente se
  guarda en notificaciones.json; la contraseña de aplicación SOLO en el almacén
  de credenciales del sistema. La contraseña nunca se devuelve a la interfaz.
- Construir y enviar un ÚNICO correo por grupo de dispositivos nuevos. El grupo
  lo entrega el monitoreo (los dispositivos nuevos de un mismo ciclo). No se
  envía un correo por dispositivo.
- Enviar en segundo plano (hilo propio): el monitoreo nunca se bloquea ni se
  detiene por un fallo SMTP. Un fallo reintentable se reintenta con una política
  prudente, sin duplicar correos ya aceptados por Gmail.

Destinatario actual: el propio correo remitente (no hay un tercer campo de
destino). La estructura queda lista para ampliarlo en el futuro.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from html import escape

from app.models.dispositivo import PerfilDispositivo
from infrastructure.correo.smtp_gmail import CorreoError, EnviadorGmail, Mensaje
from infrastructure.persistence.notificaciones_repository import JsonNotificacionesRepository
from infrastructure.secretos import CLAVE_SMTP, AlmacenSecretosError, IAlmacenSecretos

_log = logging.getLogger(__name__)

# Correo válido de forma pragmática (no RFC completa): sin espacios, con @ y dominio.
_RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ASUNTO = "CYBERA - Detección de nuevos dispositivos en la red"
MAX_REINTENTOS = 2
ESPERA_REINTENTO_S = 30.0
NO_DISPONIBLE = "No disponible"


class ConfiguracionCorreoError(ValueError):
    """Datos de configuración inválidos (correo o contraseña)."""


def correo_valido(correo: str) -> bool:
    return bool(_RE_CORREO.match(correo.strip()))


@dataclass(frozen=True)
class EstadoConfiguracion:
    remitente: str | None
    tiene_contrasena: bool

    @property
    def configurado(self) -> bool:
        return bool(self.remitente) and self.tiene_contrasena


class NotificacionService:
    def __init__(self, repositorio: JsonNotificacionesRepository, almacen: IAlmacenSecretos,
                 enviador: EnviadorGmail | None = None,
                 reloj: Callable[[], datetime] = datetime.now,
                 asincrono: bool = True, espera_reintento_s: float = ESPERA_REINTENTO_S) -> None:
        self._repo = repositorio
        self._almacen = almacen
        self._enviador = enviador or EnviadorGmail()
        self._reloj = reloj
        self._asincrono = asincrono
        self._espera_reintento = espera_reintento_s
        self._cola: queue.Queue = queue.Queue()
        self._hilo: threading.Thread | None = None
        self._detener = threading.Event()
        self._lock = threading.Lock()

    # --- Configuración ------------------------------------------------------------

    def estado(self) -> EstadoConfiguracion:
        """Estado actual. Nunca expone la contraseña, solo si existe."""
        remitente = self._repo.remitente()
        return EstadoConfiguracion(remitente=remitente, tiene_contrasena=self._tiene_contrasena())

    def esta_configurado(self) -> bool:
        return self.estado().configurado

    def guardar_config(self, remitente: str, contrasena: str | None) -> EstadoConfiguracion:
        """Guarda la configuración SMTP.

        ``contrasena`` None o vacía NO borra la contraseña ya guardada (evita que
        un campo vacío al editar sobrescriba una credencial válida). Si no había
        contraseña previa, es obligatoria.
        """
        remitente = (remitente or "").strip()
        if not remitente:
            raise ConfiguracionCorreoError("Indique el correo electrónico remitente.")
        if not correo_valido(remitente):
            raise ConfiguracionCorreoError("El correo electrónico no tiene un formato válido.")
        contrasena = (contrasena or "").strip()
        if not contrasena and not self._tiene_contrasena():
            raise ConfiguracionCorreoError(
                "Indique la contraseña de aplicación de Gmail la primera vez que configure el correo.")
        if contrasena:
            try:
                self._almacen.guardar(CLAVE_SMTP, contrasena)
            except AlmacenSecretosError as error:
                raise ConfiguracionCorreoError(str(error)) from error
        self._repo.guardar_remitente(remitente)
        return self.estado()

    def _tiene_contrasena(self) -> bool:
        try:
            return bool(self._almacen.leer(CLAVE_SMTP))
        except AlmacenSecretosError:
            return False

    def _credenciales(self) -> tuple[str, str]:
        remitente = self._repo.remitente()
        if not remitente:
            raise ConfiguracionCorreoError("No hay un correo remitente configurado.")
        try:
            contrasena = self._almacen.leer(CLAVE_SMTP)
        except AlmacenSecretosError as error:
            raise ConfiguracionCorreoError(str(error)) from error
        if not contrasena:
            raise ConfiguracionCorreoError("No hay una contraseña de aplicación configurada.")
        return remitente, contrasena

    # --- Correo de prueba ---------------------------------------------------------

    def enviar_prueba(self) -> None:
        """Envía un correo de prueba al remitente. Síncrono: propaga el resultado real.

        El controlador lo ejecuta en segundo plano para no bloquear la interfaz.
        """
        remitente, contrasena = self._credenciales()
        ahora = self._reloj()
        texto = ("Este es un correo de prueba de CYBERA.\n\n"
                 "Si lo recibió, la configuración de notificaciones por correo es correcta.\n"
                 f"Fecha y hora: {ahora:%d/%m/%Y %H:%M:%S}")
        html = (f"<html><body style=\"font-family:Segoe UI,Arial,sans-serif;color:#1F2937\">"
                f"<h2 style=\"color:#14213D\">CYBERA</h2>"
                f"<p>Este es un <b>correo de prueba</b> de CYBERA.</p>"
                f"<p>Si lo recibió, la configuración de notificaciones por correo es correcta.</p>"
                f"<p style=\"color:#64748B\">Fecha y hora: {escape(f'{ahora:%d/%m/%Y %H:%M:%S}')}</p>"
                f"</body></html>")
        self._enviador.enviar(remitente, contrasena,
                              Mensaje(destinatario=remitente, asunto="CYBERA - Correo de prueba",
                                      texto=texto, html=html))

    # --- Notificación de dispositivos nuevos --------------------------------------

    def notificar_nuevos(self, perfiles: Sequence[PerfilDispositivo]) -> None:
        """Encola UN correo con todos los dispositivos nuevos del grupo recibido.

        No bloquea: el envío ocurre en el hilo de trabajo. Si el correo no está
        configurado, no hace nada (el monitoreo sigue normal).
        """
        if not perfiles or not self.esta_configurado():
            return
        detectado = self._reloj().replace(microsecond=0)
        datos = [self._datos_dispositivo(p) for p in perfiles]
        mensaje = self._construir_mensaje(datos, detectado)
        if self._asincrono:
            self._asegurar_hilo()
            self._cola.put((mensaje, 0))
        else:
            self._enviar_con_reintento(mensaje, 0)

    # --- Hilo de envío ------------------------------------------------------------

    def _asegurar_hilo(self) -> None:
        with self._lock:
            if self._hilo is None or not self._hilo.is_alive():
                self._detener.clear()
                self._hilo = threading.Thread(target=self._bucle, name="cybera-correo", daemon=True)
                self._hilo.start()

    def _bucle(self) -> None:
        while not self._detener.is_set():
            try:
                mensaje, intento = self._cola.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._enviar_con_reintento(mensaje, intento)
            finally:
                self._cola.task_done()

    def _enviar_con_reintento(self, mensaje: Mensaje, intento: int) -> None:
        remitente = contrasena = None
        try:
            remitente, contrasena = self._credenciales()
        except ConfiguracionCorreoError as error:
            _log.warning("Notificación por correo no enviada: %s", error)
            return
        # Destinatario actual: el propio remitente (ampliable a un destino propio).
        if not mensaje.destinatario:
            mensaje = replace(mensaje, destinatario=remitente)
        try:
            self._enviador.enviar(remitente, contrasena, mensaje)
            _log.info("Notificación de dispositivos nuevos enviada.")
        except CorreoError as error:
            if error.reintentable and intento < MAX_REINTENTOS:
                _log.warning("Fallo al enviar la notificación (%s). Reintento %d/%d.",
                             error, intento + 1, MAX_REINTENTOS)
                self._reencolar(mensaje, intento + 1)
            else:
                _log.error("Notificación por correo descartada tras el fallo: %s", error)
        except Exception as error:  # noqa: BLE001 - nunca detiene el monitoreo
            _log.error("Error inesperado al enviar la notificación: %s", type(error).__name__)

    def _reencolar(self, mensaje: Mensaje, intento: int) -> None:
        if not self._asincrono:
            return
        def _demora() -> None:
            if not self._detener.wait(self._espera_reintento):
                self._cola.put((mensaje, intento))
        threading.Thread(target=_demora, name="cybera-correo-reintento", daemon=True).start()

    def detener(self) -> None:
        """Cierre de la aplicación: deja de reintentar y espera un envío en curso."""
        self._detener.set()
        hilo = self._hilo
        if hilo is not None and hilo.is_alive():
            hilo.join(timeout=5)

    # --- Construcción del mensaje -------------------------------------------------

    @staticmethod
    def _datos_dispositivo(perfil: PerfilDispositivo) -> dict:
        return {
            "nombre": perfil.hostname or perfil.alias or None,
            "mac": perfil.mac or None,
            "ip": perfil.ip or None,
            "fabricante": perfil.fabricante or None,
            "estado": perfil.estado.value if perfil.estado else None,
        }

    def _construir_mensaje(self, datos: list[dict], detectado: datetime) -> Mensaje:
        cantidad = len(datos)
        if cantidad == 1:
            encabezado = "Se ha detectado un nuevo dispositivo conectado a la red."
        else:
            encabezado = f"Se han detectado {cantidad} nuevos dispositivos conectados a la red."
        marca = f"{detectado:%d/%m/%Y %H:%M:%S}"
        return Mensaje(destinatario="", asunto=ASUNTO,
                       texto=self._texto(encabezado, datos, marca),
                       html=self._html(encabezado, datos, marca))

    @staticmethod
    def _mostrar(valor: str | None) -> str:
        return valor if valor else NO_DISPONIBLE

    def _texto(self, encabezado: str, datos: list[dict], marca: str) -> str:
        lineas = [encabezado, "", f"Fecha y hora de detección: {marca}", ""]
        for i, d in enumerate(datos, start=1):
            lineas.append(f"Dispositivo {i}:")
            lineas.append(f"  - Nombre: {self._mostrar(d['nombre'])}")
            lineas.append(f"  - Dirección MAC: {self._mostrar(d['mac'])}")
            lineas.append(f"  - Dirección IP: {self._mostrar(d['ip'])}")
            lineas.append(f"  - Fabricante: {self._mostrar(d['fabricante'])}")
            lineas.append(f"  - Estado: {self._mostrar(d['estado'])}")
            lineas.append("")
        lineas.append("— CYBERA · Control y aislamiento")
        return "\n".join(lineas)

    def _html(self, encabezado: str, datos: list[dict], marca: str) -> str:
        filas = []
        for i, d in enumerate(datos, start=1):
            celdas = [str(i), self._mostrar(d["nombre"]), self._mostrar(d["mac"]),
                      self._mostrar(d["ip"]), self._mostrar(d["fabricante"]), self._mostrar(d["estado"])]
            tds = "".join(f"<td style=\"padding:8px 12px;border-bottom:1px solid #E5EAF1\">"
                          f"{escape(c)}</td>" for c in celdas)
            filas.append(f"<tr>{tds}</tr>")
        cabeceras = "".join(
            f"<th style=\"padding:10px 12px;text-align:left;background:#2563EB;color:white;"
            f"font-size:13px\">{escape(c)}</th>"
            for c in ("#", "Nombre", "Dirección MAC", "Dirección IP", "Fabricante", "Estado"))
        return (
            "<html><body style=\"font-family:Segoe UI,Arial,sans-serif;color:#1F2937\">"
            "<h2 style=\"color:#14213D;margin-bottom:4px\">CYBERA</h2>"
            "<p style=\"color:#64748B;margin-top:0\">Control y aislamiento</p>"
            f"<p style=\"font-size:15px\">{escape(encabezado)}</p>"
            f"<p style=\"color:#64748B\">Fecha y hora de detección: {escape(marca)}</p>"
            "<table style=\"border-collapse:collapse;width:100%;font-size:13px\">"
            f"<thead><tr>{cabeceras}</tr></thead><tbody>{''.join(filas)}</tbody></table>"
            "<p style=\"color:#94A3B8;font-size:12px;margin-top:18px\">"
            "Este es un mensaje automático de CYBERA.</p>"
            "</body></html>")
