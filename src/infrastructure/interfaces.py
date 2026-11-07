"""Contratos internos (Arquitectura, sección 15.1).

Los servicios dependen de estas abstracciones; los adaptadores concretos de
Windows y de archivos JSON las implementan. Así, cambiar la técnica de
descubrimiento o el formato de almacenamiento no afecta a la lógica ni a la vista.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from enum import Enum

from app.models.aislamiento import AccionAislamiento
from app.models.configuracion import ConfiguracionSistema
from app.models.dispositivo import ObservacionRed
from app.models.dispositivo_confiable import DispositivoConfiable
from app.models.evento_bitacora import EventoBitacora
from app.models.interfaz_red import InterfazRed
from app.models.operacion_aislamiento import OperacionAislamiento


class EstadoContencion(Enum):
    """Estado de CONTENCIÓN que el motor informa para una MAC (corrección H3).

    Describe lo que el motor hace, NO la conectividad del dispositivo:

    - CONTENCION_APLICADA: el motor confirma que aplica contención al objetivo.
    - SIN_CONTENCION: el motor confirma que NO aplica contención al objetivo.
      No significa que el dispositivo tenga conectividad.
    - DESCONOCIDO: el motor no puede determinarlo. Es la respuesta obligatoria
      para una MAC que el motor no conoce (p. ej. tras reiniciar).

    Sustituye a ``EstadoRed`` (AISLADO/ACTIVO/DESCONOCIDO), cuyo valor ACTIVO
    («conectividad normal») era ambiguo.
    """

    CONTENCION_APLICADA = "CONTENCION_APLICADA"
    SIN_CONTENCION = "SIN_CONTENCION"
    DESCONOCIDO = "DESCONOCIDO"


class INetworkInterface(ABC):
    @abstractmethod
    def list_interfaces(self) -> list[InterfazRed]:
        """Interfaces de red reales que expone el sistema operativo."""


class IArpProbe(ABC):
    """Obtención de pares IP–MAC presentes en el segmento local."""

    @abstractmethod
    def sondear(self, ips: list[str], ip_origen: str,
                cancelar: threading.Event) -> list[ObservacionRed]:
        """Envía solicitudes ARP activas y devuelve las que obtuvieron respuesta."""

    @abstractmethod
    def vecinos_alcanzables(self, indice_interfaz: int) -> list[ObservacionRed]:
        """Entradas de la tabla de vecinos que el sistema confirma como alcanzables."""


class IOuiResolver(ABC):
    @abstractmethod
    def fabricante(self, mac: str) -> str | None:
        """Fabricante registrado para el bloque OUI de la MAC, o None."""


class IHostnameResolver(ABC):
    @abstractmethod
    def resolver(self, ip: str) -> str | None:
        """Nombre de host de la IP, o None si no se puede resolver."""


class IWhitelistRepository(ABC):
    @abstractmethod
    def exists(self, mac: str) -> bool: ...

    @abstractmethod
    def add(self, dispositivo: DispositivoConfiable) -> None: ...

    @abstractmethod
    def remove(self, mac: str) -> None: ...

    @abstractmethod
    def list(self) -> list[DispositivoConfiable]: ...

    @abstractmethod
    def actualizar_alias(self, mac: str, alias: str | None) -> DispositivoConfiable:
        """Cambia solo el alias del registro activo de ``mac`` (no su identidad)."""


class ISettingsRepository(ABC):
    @abstractmethod
    def load(self) -> ConfiguracionSistema: ...

    @abstractmethod
    def save(self, configuracion: ConfiguracionSistema) -> None: ...


class IIsolationRepository(ABC):
    """Persistencia del aislamiento (aislamientos.json).

    Guarda dos colecciones en el MISMO archivo para poder actualizarlas en una
    sola escritura atómica:

    - contenciones (``AccionAislamiento``): aislamientos confirmados por el motor.
    - operaciones (``OperacionAislamiento``): solicitudes y su resultado.
    """

    # ``crear``/``finalizar`` NO forman parte del contrato (corrección H8): una
    # contención solo nace o termina mediante ``resolver`` con una operación
    # CONFIRMED, es decir, a través de IsolationService y del motor.

    @abstractmethod
    def activos(self) -> list[AccionAislamiento]: ...

    @abstractmethod
    def macs_activas(self) -> set[str]: ...

    @abstractmethod
    def operaciones(self, mac: str | None = None) -> list[OperacionAislamiento]:
        """Historial de operaciones (de una MAC o de todas), en orden de registro."""

    @abstractmethod
    def registrar_solicitud(self, operacion: OperacionAislamiento) -> None:
        """Guarda una operación REQUESTED. Rechaza (ValueError) si la MAC ya tiene
        una operación en curso o si la transición no corresponde a la contención."""

    @abstractmethod
    def resolver(self, operacion: OperacionAislamiento,
                 contencion: AccionAislamiento | None = None) -> None:
        """Sustituye la operación REQUESTED por su resultado terminal y, si es un
        CONFIRMED, crea (AISLAR) o finaliza (DESBLOQUEAR) la contención en la
        misma escritura."""

    @abstractmethod
    def marcar_interrumpidas(self, fecha, mac: str | None = None) -> list[OperacionAislamiento]:
        """Pasa a UNCERTAIN/INTERRUMPIDA las operaciones REQUESTED huérfanas."""

    @abstractmethod
    def descartar(self, mac: str) -> None:
        """(Manual) Descarta una situación de aislamiento para una MAC: elimina el
        aislamiento activo y las operaciones/resoluciones pendientes de esa MAC.
        Se usa para retirar explícitamente un dispositivo de la contención (p. ej. una
        recuperación bloqueada) y permitir que el escaneo lo detecte de nuevo."""


class IBitacoraRepository(ABC):
    """Persistencia del historial de eventos (módulo Bitácora).

    Guarda la bitácora en un archivo local (``bitacora.json``) mediante el mismo
    mecanismo de almacenamiento que el resto de datos (``JsonFile``, escritura
    atómica). El módulo de Reportes podrá reutilizar los mismos registros a través
    de este contrato, sin duplicar la lógica de almacenamiento.
    """

    @abstractmethod
    def agregar(self, evento: EventoBitacora) -> EventoBitacora:
        """Añade un evento al final del historial y lo persiste."""

    @abstractmethod
    def eventos(self) -> list[EventoBitacora]:
        """Devuelve el historial completo en orden de registro."""

    @abstractmethod
    def vaciar(self) -> None:
        """Elimina todos los eventos registrados (depuración manual, CU-10)."""


class ErrorMotorAislamiento(Exception):
    """Base de los errores que un motor de aislamiento puede lanzar."""


class OperacionNoEjecutadaError(ErrorMotorAislamiento):
    """El motor GARANTIZA que no modificó nada en la red (p. ej. falló una
    comprobación previa antes de enviar cualquier trama). IsolationService la
    registra como FAILED (efecto conocido). Cualquier otra excepción se trata
    como resultado INCIERTO (UNCERTAIN) y deja la MAC pendiente de recuperación."""


class INetworkIsolation(ABC):
    """Motor de red de Capa 2 (Arquitectura, 10.2). Contrato que deberá cumplir
    ``WindowsIsolationEngine``. Ver la especificación completa en el README,
    sección «Contrato de WindowsIsolationEngine».

    Resumen (lo exige IsolationService):

    - ``disponible()``: rápido, sin efectos sobre la red y sin excepciones; False
      si faltan privilegios, adaptador o controlador de captura.
    - ``isolate``/``release`` solo SOLICITAN el cambio, son idempotentes y deben
      terminar (o lanzar) en un tiempo acotado. Regresar sin error no prueba
      nada. ``OperacionNoEjecutadaError`` = no se tocó la red; cualquier otra
      excepción = efecto desconocido.
    - ``release`` es RESTAURADORA: debe retirar cualquier contención que el
      motor pudiera haber dejado para esa MAC, incluso de una ejecución anterior.
      Si no puede garantizarlo, ``status`` debe seguir devolviendo DESCONOCIDO.
    - ``status`` es la única evidencia, no tiene efectos y devuelve un
      ``EstadoContencion``: CONTENCION_APLICADA confirma un aislamiento;
      SIN_CONTENCION confirma un desbloqueo. DESCONOCIDO, cualquier otro valor
      o una excepción NO confirman nada.
    - Para una MAC sobre la que el motor no ha actuado en esta ejecución,
      ``status`` DEBE devolver DESCONOCIDO, nunca SIN_CONTENCION por defecto.
    - Ningún valor afirma conectividad: SIN_CONTENCION no prueba que el equipo
      tenga red, y CONTENCION_APLICADA no prueba por sí sola que la haya perdido.
    - Concurrencia: IsolationService nunca llama dos veces en paralelo para la
      MISMA MAC; el motor debe tolerar llamadas paralelas para MAC distintas.
    """

    def disponible(self) -> bool:
        return True

    @abstractmethod
    def isolate(self, mac: str) -> None: ...

    @abstractmethod
    def release(self, mac: str) -> None: ...

    @abstractmethod
    def status(self, mac: str) -> EstadoContencion: ...
