"""IsolationController: pantalla Aislamiento (Mockup 06).

Lista las MAC con contención registrada, con una operación en curso o
pendientes de recuperación (``IsolationService.situaciones``), y ofrece la
única acción del mockup: «Desbloquear». El desbloqueo se ejecuta fuera del hilo
de la interfaz con el ejecutor compartido; la lista se recarga cuando termina
cualquier operación de aislamiento/desbloqueo, venga de esta pantalla o de otra.

Datos de cada tarjeta: alias de la lista blanca → nombre de host detectado →
«Desconocido»; IP solo si el equipo está detectado ahora (si no, «No
disponible»); fecha de la contención registrada o de la operación incierta.
"""

from __future__ import annotations

from PySide6.QtCore import QObject

from app.controllers.ejecutor_aislamiento import DESBLOQUEAR, EjecutorAislamiento
from app.controllers.mensajes_aislamiento import texto_contencion_retirada, titulo_error_desbloqueo
from app.services.isolation_service import IsolationService, SituacionAislamiento
from app.services.monitoring_service import MonitoringService
from app.services.whitelist_service import WhitelistService
from presentation import formato
from presentation.views.isolation_view import FilaAislamiento

_ACTOR = "administrador local"


class IsolationController(QObject):
    def __init__(self, vista, aislamiento: IsolationService, lista_blanca: WhitelistService,
                 monitoreo: MonitoringService, ejecutor: EjecutorAislamiento | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vista = vista
        self._aislamiento = aislamiento
        self._lista_blanca = lista_blanca
        self._monitoreo = monitoreo
        self._ejecutor = ejecutor or EjecutorAislamiento(aislamiento, asincrono=False, parent=self)
        self._filas: dict[str, FilaAislamiento] = {}
        self._recuperaciones: set[str] = set()
        vista.mostrada.connect(self.recargar)
        vista.desbloquearSolicitado.connect(self._desbloquear)
        self._ejecutor.iniciada.connect(lambda *_: self.recargar())
        self._ejecutor.cancelada.connect(lambda *_: self.recargar())
        self._ejecutor.terminada.connect(self._operacion_terminada)
        self._ejecutor.fallida.connect(self._operacion_fallida)
        vista.quitarSolicitado.connect(self._quitar)

    def recargar(self) -> None:
        try:
            situaciones = self._aislamiento.situaciones()
        except Exception as error:  # noqa: BLE001 - p. ej. aislamientos.json dañado
            self._filas = {}
            self._vista.mostrar_mensaje(
                f"No se pudo leer el registro de aislamiento: {error}", error=True)
            return
        filas = [self._fila(s) for s in situaciones]
        self._filas = {f.mac: f for f in filas}
        self._vista.mostrar_filas(filas)

    # --- Desbloqueo ------------------------------------------------------------------

    def _desbloquear(self, mac: str) -> None:
        fila = self._filas.get(mac)
        if fila is None or not fila.puede_desbloquear:
            self.recargar()
            return
        recuperacion = mac in self._recuperaciones
        if not self._vista.confirmar_desbloqueo(fila.nombre, mac, fila.ip, recuperacion):
            return
        if not self._ejecutor.solicitar(DESBLOQUEAR, mac, _ACTOR, contexto=self):
            self._vista.advertir("Operación en curso",
                                 f"Ya hay una operación en curso para {mac}. Espere a que termine.")
        self.recargar()

    def _quitar(self, mac: str) -> None:
        """Acción manual: retirar del listado una situación «Requiere recuperación»."""
        fila = self._filas.get(mac)
        if fila is None or not fila.puede_quitar:
            self.recargar()
            return
        if not self._vista.confirmar_quitar(fila.nombre, mac, fila.ip):
            return
        try:
            self._aislamiento.descartar(mac)
        except Exception as error:  # noqa: BLE001 - errores de persistencia
            self._vista.advertir("Quitar de la lista", str(error))
            self.recargar()
            return
        self._recuperaciones.discard(mac)
        self.recargar()

    def _operacion_terminada(self, mac: str, tipo: str, contexto, resultado) -> None:
        if contexto is self and tipo == DESBLOQUEAR:
            self._vista.informar("Contención retirada",
                                 texto_contencion_retirada(mac, recuperacion=resultado is None))
        self.recargar()

    def _operacion_fallida(self, mac: str, tipo: str, contexto, error) -> None:
        if contexto is self:
            self._vista.advertir(titulo_error_desbloqueo(error), str(error))
        self.recargar()

    # --- Datos de la tarjeta ----------------------------------------------------------

    def _fila(self, situacion: SituacionAislamiento) -> FilaAislamiento:
        mac = situacion.mac
        perfil = self._perfil_en_vivo(mac)
        alias = self._alias(mac)
        nombre = alias or (perfil.hostname if perfil else None) or formato.DESCONOCIDO
        ip = (perfil.ip if perfil and perfil.ip else formato.NO_DISPONIBLE)
        texto, tono = formato.insignia_aislamiento(situacion)
        en_curso = situacion.en_curso is not None or self._ejecutor.en_curso(mac)
        if situacion.requiere_recuperacion:
            self._recuperaciones.add(mac)
        else:
            self._recuperaciones.discard(mac)
        return FilaAislamiento(
            mac=mac, nombre=nombre, ip=ip, fecha=_fecha(situacion),
            insignia=texto, tono=tono,
            ayuda=formato.texto_situacion_aislamiento(situacion),
            puede_desbloquear=(not en_curso
                               and (situacion.registrado or situacion.requiere_recuperacion)),
            puede_quitar=(situacion.requiere_recuperacion and not en_curso))

    def _perfil_en_vivo(self, mac: str):
        try:
            return self._monitoreo.perfil_detectado(mac)
        except Exception:  # noqa: BLE001 - los datos en vivo son opcionales
            return None

    def _alias(self, mac: str) -> str | None:
        try:
            registro = self._lista_blanca.buscar(mac)
        except Exception:  # noqa: BLE001
            return None
        return registro.alias if registro else None


def _fecha(situacion: SituacionAislamiento) -> str:
    if situacion.contencion is not None:
        momento = situacion.contencion.fecha_inicio
    else:
        operacion = situacion.operacion_incierta or situacion.ultima_operacion
        if operacion is None:
            return formato.NO_DISPONIBLE
        momento = operacion.fecha_solicitud
    return momento.strftime("%d/%m/%Y %H:%M")
