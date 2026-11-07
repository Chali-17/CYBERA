"""Envío de correo por Gmail SMTP.

Valores técnicos fijos (el usuario no los ve ni los introduce):
    SMTP_HOST = smtp.gmail.com
    SMTP_PORT = 465, conexión TLS implícita (SMTP_SSL). No se usa STARTTLS.
    SMTP_USER = SMTP_FROM_EMAIL = correo remitente configurado.

Los errores se traducen a mensajes propios en español. Nunca incluyen la
contraseña ni el texto completo de la conversación SMTP.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
TIEMPO_ESPERA_S = 20


@dataclass(frozen=True)
class Mensaje:
    destinatario: str
    asunto: str
    texto: str
    html: str | None = None


class CorreoError(Exception):
    """Fallo al enviar. ``reintentable`` indica si tiene sentido volver a intentarlo."""

    def __init__(self, mensaje: str, reintentable: bool) -> None:
        super().__init__(mensaje)
        self.reintentable = reintentable


class EnviadorGmail:
    def __init__(self, host: str = SMTP_HOST, puerto: int = SMTP_PORT,
                 tiempo_espera: float = TIEMPO_ESPERA_S) -> None:
        self._host = host
        self._puerto = puerto
        self._tiempo_espera = tiempo_espera

    def enviar(self, remitente: str, contrasena: str, mensaje: Mensaje) -> None:
        """Envía el mensaje. Regresa solo cuando el servidor aceptó el correo."""
        correo = EmailMessage()
        correo["Subject"] = mensaje.asunto
        correo["From"] = f"CYBERA <{remitente}>"
        correo["To"] = mensaje.destinatario
        correo["Date"] = formatdate(localtime=True)
        correo["Message-ID"] = make_msgid(domain="cybera.local")
        correo.set_content(mensaje.texto)
        if mensaje.html:
            correo.add_alternative(mensaje.html, subtype="html")

        contexto = ssl.create_default_context()
        try:
            servidor = smtplib.SMTP_SSL(self._host, self._puerto, context=contexto,
                                        timeout=self._tiempo_espera)
        except (socket.timeout, TimeoutError):
            raise CorreoError("Tiempo de espera agotado al conectar con Gmail.", True) from None
        except (OSError, smtplib.SMTPException):
            raise CorreoError("No se pudo conectar con el servidor de Gmail. "
                              "Revise la conexión a Internet.", True) from None
        try:
            try:
                servidor.login(remitente, contrasena)
            except smtplib.SMTPAuthenticationError:
                raise CorreoError("Gmail rechazó las credenciales. Verifique el correo y que la "
                                  "contraseña sea una contraseña de aplicación válida.", False) from None
            try:
                servidor.send_message(correo)
            except smtplib.SMTPRecipientsRefused:
                raise CorreoError("Gmail rechazó la dirección de destino.", False) from None
            except smtplib.SMTPSenderRefused:
                raise CorreoError("Gmail rechazó la dirección remitente.", False) from None
            except (smtplib.SMTPServerDisconnected, OSError):
                raise CorreoError("Se perdió la conexión con Gmail durante el envío.", True) from None
            except smtplib.SMTPException:
                raise CorreoError("Gmail no aceptó el mensaje.", True) from None
        finally:
            # El correo ya fue aceptado (o falló antes): un error al cerrar no
            # debe provocar un reintento ni un duplicado.
            try:
                servidor.quit()
            except Exception:  # noqa: BLE001
                pass
