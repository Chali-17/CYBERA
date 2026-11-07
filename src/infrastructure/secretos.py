"""Almacén de secretos: la contraseña de aplicación de Gmail.

La contraseña NUNCA se escribe en archivos del proyecto ni en configuracion.json.
Se guarda en el Administrador de credenciales de Windows mediante la biblioteca
``keyring`` (backend WinVault), protegido por la cuenta de usuario de Windows.

``AlmacenEnMemoria`` existe solo para las pruebas automatizadas.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

SERVICIO = "CYBERA"
CLAVE_SMTP = "smtp-gmail-app-password"


class AlmacenSecretosError(Exception):
    """El almacén seguro del sistema no está disponible o falló."""


class IAlmacenSecretos(ABC):
    @abstractmethod
    def leer(self, clave: str) -> str | None: ...

    @abstractmethod
    def guardar(self, clave: str, valor: str) -> None: ...

    @abstractmethod
    def eliminar(self, clave: str) -> None: ...


class AlmacenKeyring(IAlmacenSecretos):
    """Administrador de credenciales de Windows (vía ``keyring``)."""

    def __init__(self, servicio: str = SERVICIO) -> None:
        self._servicio = servicio

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError:
            raise AlmacenSecretosError(
                "Falta la biblioteca «keyring» (pip install -r requirements.txt).") from None
        return keyring

    def leer(self, clave: str) -> str | None:
        try:
            return self._keyring().get_password(self._servicio, clave)
        except AlmacenSecretosError:
            raise
        except Exception as error:  # noqa: BLE001 - nunca se incluye el valor
            raise AlmacenSecretosError(
                f"No se pudo leer el almacén de credenciales de Windows ({type(error).__name__}).") from None

    def guardar(self, clave: str, valor: str) -> None:
        try:
            self._keyring().set_password(self._servicio, clave, valor)
        except AlmacenSecretosError:
            raise
        except Exception as error:  # noqa: BLE001
            raise AlmacenSecretosError(
                f"No se pudo guardar en el almacén de credenciales de Windows ({type(error).__name__}).") from None

    def eliminar(self, clave: str) -> None:
        try:
            self._keyring().delete_password(self._servicio, clave)
        except Exception:  # noqa: BLE001 - no existía: nada que borrar
            pass


class AlmacenEnMemoria(IAlmacenSecretos):
    """Solo para pruebas: no persiste nada."""

    def __init__(self) -> None:
        self.valores: dict[str, str] = {}

    def leer(self, clave: str) -> str | None:
        return self.valores.get(clave)

    def guardar(self, clave: str, valor: str) -> None:
        self.valores[clave] = valor

    def eliminar(self, clave: str) -> None:
        self.valores.pop(clave, None)
