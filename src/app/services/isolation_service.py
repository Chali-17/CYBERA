"""IsolationService: frontera de seguridad del aislamiento (Arquitectura, 9.2).

Orquesta las operaciones AISLAR y DESBLOQUEAR siguiendo la máquina de estados
de ``app.models.operacion_aislamiento``. NO simula el aislamiento: solo da por
confirmado lo que el motor (``INetworkIsolation``) verifica con ``status``,
según el contrato ``EstadoContencion`` (ver ``infrastructure/interfaces.py``).

Flujo de una operación sobre una MAC normalizada::

    validar MAC y actor ── rechazo ──► error, sin operación ni escritura
        │
    reservar la MAC (coordinador único por carpeta de datos, compartido con
        │            WhitelistService y con cualquier otro IsolationService)
        │   └─ ocupada ──► OperacionEnCursoError
    comprobar reglas (lista blanca, contención registrada / recuperación pendiente)
        │   └─ no cumple ──► error, sin operación ni escritura
    PENDING ── motor ausente/no operativo ──► FAILED(NO_DISPONIBLE)  [no se escribe]
        │
    registrar REQUESTED en disco ── falla ──► FAILED(ERROR_REGISTRO) [motor no invocado]
        │
    [AISLAR] revalidar lista blanca ── autorizada ─► FAILED(AUTORIZADA) [motor no invocado]
        │
    motor.isolate/release + motor.status
        ├─ OperacionNoEjecutadaError ───────► FAILED(ERROR_MOTOR)          [efecto conocido]
        ├─ otra excepción ──────────────────► UNCERTAIN(ERROR_MOTOR)       [requiere recuperación]
        ├─ status = valor contrario ────────► FAILED(SIN_CONFIRMACION)     [efecto conocido]
        ├─ status DESCONOCIDO / inválido ───► UNCERTAIN(SIN_CONFIRMACION)  [requiere recuperación]
        └─ status exigido
             [AISLAR] revalidar lista blanca ── autorizada ─► revertir con release:
                      verificada → FAILED(AUTORIZADA); no → UNCERTAIN(REVERSION_FALLIDA)
             └─► CONFIRMED + contención (+ resuelve incertidumbres previas) [una escritura]
    liberar la reserva (siempre, en ``finally``)

Recuperación: una MAC con una operación UNCERTAIN sin resolver figura en la
pantalla Aislamiento como «Requiere recuperación». La recuperación es SIEMPRE una
acción explícita del usuario: «Desbloquear» (release + verificación). Nunca se
reintenta nada automáticamente.

Verificación (correcciones H3/H4): cada lectura de ``status`` se anota en
memoria (``SituacionAislamiento.verificacion``) y NUNCA en disco. Tras reiniciar,
una contención registrada en aislamientos.json queda «sin verificar» hasta que
el motor la vuelva a comprobar (``verificar_registrados``).
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.models.aislamiento import AccionAislamiento, EstadoAislamiento
from app.models.evento_bitacora import ResultadoEvento, TipoEvento
from app.models.mac import es_mac_de_dispositivo, normalizar_mac
from app.models.operacion_aislamiento import MotivoFallo, OperacionAislamiento, TipoOperacion
from app.services import reservas_mac
from app.services.bitacora_service import BitacoraService
from app.services.reservas_mac import MacOcupadaError, ReservasPorMac, coordinador_de_repositorio
from infrastructure.interfaces import (EstadoContencion, IBitacoraRepository, IIsolationRepository,
                                       INetworkIsolation, IWhitelistRepository, OperacionNoEjecutadaError)

_SUFIJO_SIN_MARCAR = "No se registró el dispositivo como aislado."


class AislamientoError(RuntimeError):
    """Base de los errores de aislamiento. ``operacion`` es la operación afectada,
    si llegó a existir (estado PENDING en adelante)."""

    def __init__(self, mensaje: str, operacion: OperacionAislamiento | None = None) -> None:
        super().__init__(mensaje)
        self.operacion = operacion

    @property
    def requiere_recuperacion(self) -> bool:
        """La operación quedó UNCERTAIN: su efecto de red es desconocido."""
        return self.operacion is not None and self.operacion.requiere_recuperacion


class AislamientoNoDisponibleError(AislamientoError):
    """No hay un motor de red capaz de ejecutar la operación."""


class DispositivoProtegidoError(AislamientoError):
    """La MAC está (o pasó a estar) autorizada en la lista blanca (RI-05)."""


class OperacionEnCursoError(AislamientoError):
    """La MAC ya tiene una operación de aislamiento, desbloqueo o autorización en curso."""


class TransicionNoPermitidaError(AislamientoError):
    """La solicitud no corresponde al estado actual (p. ej. aislar dos veces)."""


class RegistroAislamientoError(AislamientoError):
    """No se pudo leer o escribir aislamientos.json de forma segura."""


class AislamientoFallidoError(AislamientoError):
    """El motor no confirmó la contención del dispositivo."""


class DesbloqueoFallidoError(AislamientoError):
    """El motor no confirmó que dejó de aplicar contención."""


@dataclass(frozen=True)
class VerificacionContencion:
    """Respuesta de ``status`` obtenida en ESTA ejecución (no se persiste)."""

    estado: EstadoContencion
    fecha: datetime


@dataclass(frozen=True)
class SituacionAislamiento:
    """Vista de lectura del aislamiento de una MAC, para la interfaz.

    - ``contencion``: registro administrativo ACTIVO en aislamientos.json.
    - ``verificacion``: última respuesta del motor en esta ejecución, o None.
    """

    mac: str
    contencion: AccionAislamiento | None
    ultima_operacion: OperacionAislamiento | None
    en_curso: TipoOperacion | None
    verificacion: VerificacionContencion | None = None
    # Hay una operación UNCERTAIN sin resolver: el efecto de red es desconocido.
    requiere_recuperacion: bool = False
    # Operación incierta pendiente más reciente (evidencia para la interfaz).
    operacion_incierta: OperacionAislamiento | None = None

    @property
    def registrado(self) -> bool:
        return self.contencion is not None

    @property
    def aislado_confirmado(self) -> bool:
        """Registrado Y verificado como CONTENCION_APLICADA en esta ejecución."""
        return (self.contencion is not None and self.verificacion is not None
                and self.verificacion.estado is EstadoContencion.CONTENCION_APLICADA)


class _ReservaTraducida:
    """Adapta ``MacOcupadaError`` (reserva compartida) a ``OperacionEnCursoError``."""

    def __init__(self, gestor) -> None:
        self._gestor = gestor

    def __enter__(self):
        try:
            return self._gestor.__enter__()
        except MacOcupadaError as error:
            raise OperacionEnCursoError(str(error)) from error

    def __exit__(self, *exc):
        return self._gestor.__exit__(*exc)


class IsolationService:
    def __init__(self, repositorio: IIsolationRepository, lista_blanca: IWhitelistRepository,
                 motor: INetworkIsolation | None = None,
                 reloj: Callable[[], datetime] = datetime.now,
                 reservas: ReservasPorMac | None = None,
                 bitacora: BitacoraService | None = None) -> None:
        self._repo = repositorio
        self._lista_blanca = lista_blanca
        self._motor = motor
        self._reloj = reloj
        # Por defecto, el coordinador único de la carpeta de datos (compartido por
        # todos los servicios del proceso sobre esos archivos).
        self._reservas = reservas or coordinador_de_repositorio(repositorio)
        self._bitacora = bitacora
        self._verificaciones: dict[str, VerificacionContencion] = {}
        self._candado_verificaciones = threading.Lock()

    # --- Consultas --------------------------------------------------------------------

    @property
    def disponible(self) -> bool:
        """True solo si hay un motor de red conectado y operativo."""
        return self._motor_operativo() is not None

    def macs_aisladas(self) -> set[str]:
        """MAC con contención REGISTRADA vigente (dato administrativo; no incluye
        solicitudes y no implica verificación en esta ejecución)."""
        return self._repo.macs_activas()

    def historial(self, mac: str | None = None) -> list[OperacionAislamiento]:
        return self._repo.operaciones(normalizar_mac(mac) if mac is not None else None)

    def verificacion(self, mac: str) -> VerificacionContencion | None:
        with self._candado_verificaciones:
            return self._verificaciones.get(normalizar_mac(mac))

    def situacion(self, mac: str) -> SituacionAislamiento:
        mac = normalizar_mac(mac)
        return self._situacion(mac, self._repo.activos(), self._repo.operaciones(mac))

    def requiere_recuperacion(self, mac: str) -> bool:
        mac = normalizar_mac(mac)
        return any(o.requiere_recuperacion for o in self._repo.operaciones(mac))

    def situaciones(self) -> list[SituacionAislamiento]:
        """MAC que la pantalla Aislamiento (Mockup 06) debe listar: contención
        registrada, operación en curso o pendiente de recuperación."""
        activos = self._repo.activos()
        ops = self._repo.operaciones()
        macs = {a.mac_objetivo for a in activos}
        macs |= {o.mac_objetivo for o in ops if o.en_curso or o.requiere_recuperacion}
        macs |= {m for m, etiqueta in self._reservas.ocupadas().items()
                 if _tipo_operacion(etiqueta) is not None}
        situaciones = [self._situacion(m, activos, [o for o in ops if o.mac_objetivo == m])
                       for m in macs]
        return sorted(situaciones, key=lambda s: _fecha_referencia(s), reverse=True)

    def _situacion(self, mac: str, activos: list[AccionAislamiento],
                   ops: list[OperacionAislamiento]) -> SituacionAislamiento:
        contencion = next((a for a in activos if a.mac_objetivo == mac), None)
        ultima = ops[-1] if ops else None
        en_curso = _tipo_operacion(self._reservas.en_curso(mac))
        if en_curso is None and ultima is not None and ultima.en_curso:
            en_curso = ultima.tipo
        inciertas = [o for o in ops if o.requiere_recuperacion]
        return SituacionAislamiento(mac, contencion, ultima, en_curso, self.verificacion(mac),
                                    requiere_recuperacion=bool(inciertas),
                                    operacion_incierta=inciertas[-1] if inciertas else None)

    # --- Operaciones ------------------------------------------------------------------

    def aislar(self, mac: str, autorizado_por: str, id_alerta: str | None = None) -> AccionAislamiento:
        """Solicita aislar ``mac``. Devuelve la contención solo si el motor la confirmó."""
        mac = self._validar_mac(mac)
        actor = self._validar_actor(autorizado_por)
        with self._reservar(mac, reservas_mac.AISLAR):
            if self._leer(lambda: self._lista_blanca.exists(mac)):          # RI-05
                raise DispositivoProtegidoError(
                    f"La MAC {mac} está autorizada en la lista blanca; no se aísla (RI-05).")
            if mac in self._leer(self._repo.macs_activas):
                raise TransicionNoPermitidaError(f"La MAC {mac} ya tiene un aislamiento registrado.")

            pendiente = OperacionAislamiento(mac, TipoOperacion.AISLAR, actor, self._ahora())
            motor = self._exigir_motor(pendiente, "El aislamiento", _SUFIJO_SIN_MARCAR)
            solicitada = self._registrar(pendiente, mac, _SUFIJO_SIN_MARCAR)

            # H1: revalidar la autorización justo antes de invocar al motor.
            motivo = self._motivo_autorizacion(mac)
            if motivo is not None:
                fallida = solicitada.fallar(motivo, self._ahora(),
                                            "Revalidación previa al envío: no se invocó al motor.")
                raise DispositivoProtegidoError(
                    f"{_texto_autorizacion(motivo, mac)} No se envió nada al motor de red. "
                    f"{_SUFIJO_SIN_MARCAR}" + self._guardar_fallo(fallida), fallida)

            try:
                motor.isolate(mac)
                estado = self._consultar(motor, mac)
            except Exception as error:  # noqa: BLE001 - cualquier fallo del motor
                resultado = self._resultado_error(solicitada, mac, error)
                self._registrar_evento(solicitada, False)
                raise AislamientoFallidoError(
                    f"El motor de red falló al aislar {mac}: {error}. {_SUFIJO_SIN_MARCAR} "
                    + _texto_resultado(resultado)
                    + self._guardar_fallo(resultado), resultado) from error
            if estado is not EstadoContencion.CONTENCION_APLICADA:
                resultado = self._resultado_sin_confirmar(solicitada, estado,
                                                          EstadoContencion.SIN_CONTENCION)
                self._registrar_evento(solicitada, False)
                raise AislamientoFallidoError(
                    f"El motor de red no confirmó que aplica contención a {mac} "
                    f"(status: {_texto_estado(estado)}). {_SUFIJO_SIN_MARCAR} "
                    + _texto_resultado(resultado)
                    + self._guardar_fallo(resultado), resultado)

            # H1: revalidar la autorización antes de confirmar.
            motivo = self._motivo_autorizacion(mac)
            if motivo is not None:
                revertida, detalle = self._revertir(motor, mac)
                causa = _texto_autorizacion(motivo, mac)
                if revertida:
                    resultado = solicitada.fallar(motivo, self._ahora(), detalle)
                    consecuencia = ("La contención se revirtió y el motor confirmó que ya no "
                                    "la aplica.")
                else:
                    # Reversión fallida: se conserva la evidencia y se exige recuperación.
                    resultado = solicitada.marcar_incierta(
                        MotivoFallo.REVERSION_FALLIDA, self._ahora(),
                        f"Causa: {motivo.value}. {detalle}")
                    consecuencia = ("No se pudo verificar la reversión: el estado de contención "
                                    "es desconocido y el dispositivo requiere recuperación "
                                    "(«Desbloquear» en la pantalla Aislamiento).")
                self._registrar_evento(resultado, False)
                raise DispositivoProtegidoError(
                    f"{causa} {consecuencia} {_SUFIJO_SIN_MARCAR}"
                    + self._guardar_fallo(resultado), resultado)

            fin = self._ahora()
            accion = AccionAislamiento(mac_objetivo=mac, id_alerta_origen=id_alerta,
                                       fecha_inicio=fin, autorizado_por=actor)
            confirmada = solicitada.confirmar(fin, accion.id_aislamiento)
            try:
                self._repo.resolver(confirmada, accion)
            except Exception as error:  # noqa: BLE001
                self._registrar_evento(confirmada, False)
                raise RegistroAislamientoError(
                    f"El motor informó que aplica contención a {mac}, pero no se pudo registrar "
                    f"({error}). {_SUFIJO_SIN_MARCAR} La contención podría seguir aplicada: "
                    "estado sin verificar en el registro.", solicitada) from error
            self._registrar_evento(confirmada, True)
            return accion

    def desbloquear(self, mac: str, solicitado_por: str) -> AccionAislamiento | None:
        """Solicita retirar la contención de ``mac``. Solo se confirma si el motor
        devuelve SIN_CONTENCION; esto NO afirma que el dispositivo haya recuperado
        la conectividad.

        - Con contención registrada: la finaliza y la devuelve (INACTIVO).
        - Sin contención registrada pero PENDIENTE DE RECUPERACIÓN (operación
          UNCERTAIN): es el desbloqueo de recuperación. Devuelve None. Es la
          estrategia de recuperación segura: va hacia «sin contención» y exige
          verificación; nunca se lanza de forma automática.
        """
        mac = self._validar_mac(mac)
        actor = self._validar_actor(solicitado_por)
        with self._reservar(mac, reservas_mac.DESBLOQUEAR):
            contencion = next((a for a in self._leer(self._repo.activos)
                               if a.mac_objetivo == mac), None)
            if contencion is None and not self._leer(lambda: self.requiere_recuperacion(mac)):
                raise TransicionNoPermitidaError(
                    f"La MAC {mac} no tiene un aislamiento registrado ni una recuperación "
                    "pendiente que desbloquear.")
            sigue = ("El aislamiento sigue registrado." if contencion is not None else
                     "El dispositivo sigue pendiente de recuperación.")

            pendiente = OperacionAislamiento(
                mac, TipoOperacion.DESBLOQUEAR, actor, self._ahora(),
                id_aislamiento=contencion.id_aislamiento if contencion else None)
            motor = self._exigir_motor(pendiente, "El desbloqueo", sigue)
            solicitada = self._registrar(pendiente, mac, sigue)

            try:
                motor.release(mac)
                estado = self._consultar(motor, mac)
            except Exception as error:  # noqa: BLE001
                resultado = self._resultado_error(solicitada, mac, error)
                self._registrar_evento(solicitada, False)
                raise DesbloqueoFallidoError(
                    f"El motor de red falló al desbloquear {mac}: {error}. {sigue} "
                    + _texto_resultado(resultado)
                    + self._guardar_fallo(resultado), resultado) from error
            if estado is not EstadoContencion.SIN_CONTENCION:
                resultado = self._resultado_sin_confirmar(solicitada, estado,
                                                          EstadoContencion.CONTENCION_APLICADA)
                self._registrar_evento(solicitada, False)
                raise DesbloqueoFallidoError(
                    f"El motor de red no confirmó que dejó de aplicar contención a {mac} "
                    f"(status: {_texto_estado(estado)}). {sigue} "
                    + _texto_resultado(resultado)
                    + self._guardar_fallo(resultado), resultado)

            fin = self._ahora()
            confirmada = solicitada.confirmar(fin)
            try:
                self._repo.resolver(confirmada)
            except Exception as error:  # noqa: BLE001
                self._registrar_evento(confirmada, False)
                raise RegistroAislamientoError(
                    f"El motor informó que dejó de aplicar contención a {mac}, pero no se pudo "
                    f"registrar ({error}). {sigue}", solicitada) from error
            self._registrar_evento(confirmada, True)
            if contencion is None:
                return None
            return dataclasses.replace(contencion, fecha_fin=fin,
                                       estado=EstadoAislamiento.INACTIVO)

    def descartar(self, mac: str) -> None:
        """(Manual) Descarta una situación de aislamiento para una MAC.

        Elimina el aislamiento activo y las operaciones/resoluciones pendientes de
        esa MAC, de modo que deje de figurar como aislada y el escaneo pueda volver a
        detectar al equipo. Es la salida operativa cuando una situación de
        «Requiere recuperación» queda bloqueada: el operador la retira explícitamente
        en lugar de reintentar el desbloqueo automáticamente.
        """
        mac_objetivo = self._validar_mac(mac)
        self._leer(lambda: self._repo.descartar(mac_objetivo))

    def recuperar_interrumpidas(self) -> list[OperacionAislamiento]:
        """Al iniciar: toda operación REQUESTED en disco quedó sin verificar (la
        aplicación se cerró a mitad). Pasa a UNCERTAIN/INTERRUMPIDA (requiere
        recuperación); nunca a CONFIRMED. Las contenciones registradas se
        conservan tal cual. No se reintenta nada."""
        return self._repo.marcar_interrumpidas(self._ahora())

    def _registrar_evento(self, operacion: OperacionAislamiento, exito: bool) -> None:
        """Registra en la bitácora el resultado de una operación de aislamiento/desbloqueo (CU-10).

        - ``exito``: la operación llegó a CONFIRMED con el resultado esperado (el motor
          verificó). El evento queda con ``ResultadoEvento.EXITOSO``.
        - Cualquier otro estado terminal (FAILED o UNCERTAIN): el evento queda con
          ``ResultadoEvento.FALLO`` y se distingue claramente del intento fallido.
        Los errores de escritura no se propagan: la bitácora registra y avisa.
        """
        if self._bitacora is None:
            return
        tipo = TipoEvento.BLOQUEO if operacion.tipo is TipoOperacion.AISLAR else TipoEvento.DESBLOQUEO
        self._bitacora.registrar(
            tipo, operacion.mac_objetivo, None, None,
            ResultadoEvento.EXITOSO if exito else ResultadoEvento.FALLO,
            descripcion=self._descripcion_evento(operacion, exito),
            actor=operacion.solicitado_por)

    @staticmethod
    def _descripcion_evento(operacion: OperacionAislamiento, exito: bool) -> str:
        if exito:
            return (f"El aislamiento o desbloqueo de {operacion.mac_objetivo} se confirmó con el "
                    "motor de red.")
        motivo = operacion.motivo_fallo.value if operacion.motivo_fallo else "resultado no confirmado"
        return (f"La operación de aislamiento o desbloqueo sobre {operacion.mac_objetivo} no se "
                f"completó ({motivo}).")

    def _resultado_error(self, solicitada: OperacionAislamiento, mac: str,
                         error: Exception) -> OperacionAislamiento:
        """Excepción del motor: FAILED solo si el motor garantiza que no tocó la
        red (OperacionNoEjecutadaError); si no, UNCERTAIN."""
        if isinstance(error, OperacionNoEjecutadaError):
            return solicitada.fallar(MotivoFallo.ERROR_MOTOR, self._ahora(), str(error))
        self._anotar(mac, EstadoContencion.DESCONOCIDO)
        return solicitada.marcar_incierta(MotivoFallo.ERROR_MOTOR, self._ahora(), str(error))

    def _resultado_sin_confirmar(self, solicitada: OperacionAislamiento, estado,
                                 contrario: EstadoContencion) -> OperacionAislamiento:
        """status() distinto del exigido: FAILED si es el valor contrario del
        contrato (efecto conocido); UNCERTAIN si es DESCONOCIDO o inválido."""
        detalle = f"status devolvió {_texto_estado(estado)}"
        if estado is contrario:
            return solicitada.fallar(MotivoFallo.SIN_CONFIRMACION, self._ahora(), detalle)
        return solicitada.marcar_incierta(MotivoFallo.SIN_CONFIRMACION, self._ahora(), detalle)

    def verificar_registrados(self) -> dict[str, VerificacionContencion]:
        """Consulta al motor el estado de cada contención registrada. Solo anota
        la respuesta en memoria; NO modifica aislamientos.json. Sin motor
        operativo no hace nada (las contenciones quedan «sin verificar»)."""
        motor = self._motor_operativo()
        if motor is None:
            return {}
        resultado = {}
        for mac in sorted(self._repo.macs_activas()):
            try:
                with self._reservar(mac, reservas_mac.VERIFICAR):
                    try:
                        self._consultar(motor, mac)
                    except Exception:  # noqa: BLE001 - queda DESCONOCIDO
                        self._anotar(mac, EstadoContencion.DESCONOCIDO)
            except OperacionEnCursoError:
                continue                      # Otra operación la está tratando.
            resultado[mac] = self.verificacion(mac)
        return resultado

    # --- Auxiliares -------------------------------------------------------------------

    def _ahora(self) -> datetime:
        return self._reloj().replace(microsecond=0)

    def _reservar(self, mac: str, operacion: str) -> _ReservaTraducida:
        return _ReservaTraducida(self._reservas.reservar(mac, operacion))

    def _anotar(self, mac: str, estado: EstadoContencion) -> None:
        with self._candado_verificaciones:
            self._verificaciones[mac] = VerificacionContencion(estado, self._ahora())

    def _consultar(self, motor: INetworkIsolation, mac: str):
        """Llama a ``status`` y anota la respuesta. Un valor ajeno al contrato se
        anota como DESCONOCIDO y se devuelve tal cual (no confirmará nada)."""
        estado = motor.status(mac)
        self._anotar(mac, estado if isinstance(estado, EstadoContencion)
                     else EstadoContencion.DESCONOCIDO)
        return estado

    def _motivo_autorizacion(self, mac: str) -> MotivoFallo | None:
        try:
            return MotivoFallo.AUTORIZADA if self._lista_blanca.exists(mac) else None
        except Exception:  # noqa: BLE001 - si no se puede comprobar RI-05, no se sigue
            return MotivoFallo.AUTORIZACION_NO_VERIFICABLE

    def _revertir(self, motor: INetworkIsolation, mac: str) -> tuple[bool, str]:
        try:
            motor.release(mac)
            estado = self._consultar(motor, mac)
        except Exception as error:  # noqa: BLE001
            self._anotar(mac, EstadoContencion.DESCONOCIDO)
            return False, f"Reversión fallida: {error}. Estado de contención desconocido."
        if estado is EstadoContencion.SIN_CONTENCION:
            return True, "Contención revertida; el motor confirmó SIN_CONTENCION."
        return False, (f"Reversión no confirmada (status: {_texto_estado(estado)}). "
                       "Estado de contención desconocido.")

    @staticmethod
    def _validar_mac(mac: str) -> str:
        try:
            mac = normalizar_mac(mac)                                       # RI-03
        except ValueError as error:
            raise AislamientoError(str(error)) from error
        if not es_mac_de_dispositivo(mac):
            raise AislamientoError(
                f"La dirección {mac} no identifica a un dispositivo aislable (difusión o nula).")
        return mac

    @staticmethod
    def _validar_actor(actor: str) -> str:
        texto = " ".join(str(actor or "").split())
        if not texto:
            raise AislamientoError("La operación requiere identificar al usuario que la solicita.")
        return texto

    @staticmethod
    def _leer(consulta: Callable):
        try:
            return consulta()
        except Exception as error:  # noqa: BLE001 - p. ej. JSON dañado
            raise RegistroAislamientoError(
                f"No se pudo consultar el estado actual ({error}). No se envió ninguna "
                "solicitud al motor de red.") from error

    def _motor_operativo(self) -> INetworkIsolation | None:
        if self._motor is None:
            return None
        try:
            return self._motor if self._motor.disponible() else None
        except Exception:  # noqa: BLE001 - un motor que no responde no está disponible
            return None

    def _exigir_motor(self, pendiente: OperacionAislamiento, que: str,
                      consecuencia: str) -> INetworkIsolation:
        motor = self._motor_operativo()
        if motor is None:
            if self._motor is None:
                razon = "No hay un motor de red de Capa 2 conectado (módulo de defensa activa)."
            else:
                # El motor ESTÁ conectado pero se declara no disponible: se informa su
                # motivo real. No es un fallo de integración ni de privilegios.
                razon = getattr(self._motor, "motivo_no_disponible", None) or (
                    "El motor de red de Capa 2 informa que no está disponible.")
            raise AislamientoNoDisponibleError(
                f"{que} no está disponible: {razon} {consecuencia}",
                pendiente.fallar(MotivoFallo.NO_DISPONIBLE, self._ahora()))
        return motor

    def _registrar(self, pendiente: OperacionAislamiento, mac: str,
                   consecuencia: str) -> OperacionAislamiento:
        """PENDING → REQUESTED, escrito en disco ANTES de invocar al motor."""
        solicitada = pendiente.solicitar()
        try:
            # Con la MAC reservada y la instancia única garantizada en main.py,
            # cualquier REQUESTED previo en disco es huérfano de una ejecución anterior.
            self._repo.marcar_interrumpidas(self._ahora(), mac)
            self._repo.registrar_solicitud(solicitada)
        except Exception as error:  # noqa: BLE001
            raise RegistroAislamientoError(
                f"No se pudo registrar la solicitud ({error}). No se envió nada al motor "
                f"de red. {consecuencia}",
                pendiente.fallar(MotivoFallo.ERROR_REGISTRO, self._ahora(), str(error))) from error
        return solicitada

    def _guardar_fallo(self, fallida: OperacionAislamiento) -> str:
        """Registra el FAILED. Si tampoco se puede escribir, lo indica en el mensaje:
        la solicitud seguirá como REQUESTED y se tratará como interrumpida."""
        try:
            self._repo.resolver(fallida)
        except Exception as error:  # noqa: BLE001
            return (f" Además, no se pudo registrar el fallo ({error}); la solicitud "
                    "quedará como interrumpida y sin verificar.")
        return ""


def _tipo_operacion(etiqueta: str | None) -> TipoOperacion | None:
    try:
        return TipoOperacion(etiqueta) if etiqueta else None
    except ValueError:
        return None          # AUTORIZAR / VERIFICAR no son operaciones de aislamiento.


def _fecha_referencia(situacion: SituacionAislamiento) -> datetime:
    if situacion.contencion is not None:
        return situacion.contencion.fecha_inicio
    operacion = situacion.operacion_incierta or situacion.ultima_operacion
    return operacion.fecha_solicitud if operacion is not None else datetime.min


def _texto_resultado(resultado: OperacionAislamiento) -> str:
    if resultado.requiere_recuperacion:
        return ("El resultado es INCIERTO: el estado de contención es desconocido y el "
                "dispositivo requiere recuperación («Desbloquear» en la pantalla Aislamiento).")
    return "El motor no dejó la contención solicitada."


def _texto_estado(estado) -> str:
    return estado.value if isinstance(estado, EstadoContencion) else repr(estado)


def _texto_autorizacion(motivo: MotivoFallo, mac: str) -> str:
    if motivo is MotivoFallo.AUTORIZADA:
        return f"La MAC {mac} pasó a estar autorizada en la lista blanca durante la operación (RI-05)."
    return (f"No se pudo comprobar si {mac} está autorizada en la lista blanca; por seguridad "
            "no se continúa (RI-05).")
