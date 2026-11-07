"""DeviceController: coordina la vista Dispositivos, el monitoreo, la lista
blanca y el aislamiento."""

from __future__ import annotations

from PySide6.QtCore import QObject

from app.controllers.ejecutor_aislamiento import AISLAR, EjecutorAislamiento
# Reexportados: otros módulos y pruebas los importan desde aquí.
from app.controllers.mensajes_aislamiento import (texto_contencion_confirmada,  # noqa: F401
                                                  titulo_error_aislamiento)
from app.controllers.monitoring_controller import MonitoringController
from app.models.dispositivo import PerfilDispositivo
from app.models.dispositivo_confiable import OrigenRegistro
from app.services.bitacora_service import BitacoraService
from app.services.isolation_service import IsolationService
from app.services.monitoring_service import MonitoringService, ResultadoCiclo, TipoResultado
from app.services.whitelist_service import DispositivoYaAutorizadoError, WhitelistService
from presentation.views.review_dialog import ACCION_AISLAR, ACCION_AUTORIZAR

_TIPOS_ERROR = {TipoResultado.ERROR, TipoResultado.INTERFAZ_NO_DISPONIBLE}
# Actor que autoriza/aísla. Sin módulo de sesión aún; el administrador local.
_ACTOR = "administrador local"


class DeviceController(QObject):
    def __init__(self, vista, monitoreo: MonitoringController,
                 servicio_monitoreo: MonitoringService, lista_blanca: WhitelistService,
                 aislamiento: IsolationService, parent: QObject | None = None,
                 ejecutor: EjecutorAislamiento | None = None,
                 bitacora: BitacoraService | None = None) -> None:
        super().__init__(parent)
        self._vista = vista
        self._monitoreo = monitoreo
        self._servicio_monitoreo = servicio_monitoreo
        self._lista_blanca = lista_blanca
        self._aislamiento = aislamiento
        self._bitacora = bitacora
        # app/main.py inyecta el ejecutor asíncrono compartido; sin él (pruebas)
        # se usa uno síncrono con las mismas señales.
        self._ejecutor = ejecutor or EjecutorAislamiento(aislamiento, asincrono=False, parent=self)
        self._ejecutor.terminada.connect(self._operacion_terminada)
        self._ejecutor.fallida.connect(self._operacion_fallida)
        self._actuales: dict[str, PerfilDispositivo] = {}
        monitoreo.resultadoCiclo.connect(self._mostrar_resultado)
        monitoreo.escaneoIniciado.connect(self._vista.mostrar_busqueda)
        vista.revisarSolicitado.connect(self._revisar)

    def _mostrar_resultado(self, resultado: ResultadoCiclo) -> None:
        if resultado.tipo is TipoResultado.ACTUALIZADO:
            self._publicar(resultado.dispositivos)
            return
        if resultado.tipo is TipoResultado.CANCELADO:
            return
        self._actuales = {}
        self._vista.mostrar_mensaje(resultado.mensaje or "", error=resultado.tipo in _TIPOS_ERROR)

    def _publicar(self, dispositivos: list[PerfilDispositivo]) -> None:
        self._actuales = {d.mac: d for d in dispositivos}
        self._vista.mostrar_dispositivos(dispositivos)

    def _revisar(self, mac: str) -> None:
        perfil = self._actuales.get(mac)
        if perfil is None:
            self._vista.advertir("Revisar dispositivo",
                                 "El dispositivo ya no figura en el inventario actual.")
            return
        accion, alias = self._vista.solicitar_decision(perfil)
        if accion == ACCION_AUTORIZAR:
            self._autorizar(mac, perfil, alias)
        elif accion == ACCION_AISLAR:
            self._aislar(mac, perfil)

    def _autorizar(self, mac: str, perfil: PerfilDispositivo, alias: str | None) -> None:
        try:
            registro = self._lista_blanca.autorizar(mac, alias, OrigenRegistro.ESCANEO)
        except DispositivoYaAutorizadoError as error:
            self._vista.advertir("Autorizar dispositivo", str(error))
        except Exception as error:  # noqa: BLE001 - p. ej. archivo dañado o sin permisos
            # El dispositivo permanece visible porque la autorización no se confirmó.
            self._vista.advertir("No se pudo autorizar", str(error))
            return
        else:
            nombre = registro.alias or perfil.hostname or registro.mac
            self._vista.informar("Dispositivo autorizado",
                                 f"«{nombre}» ({registro.mac}) se agregó a la lista blanca.")
            if self._bitacora is not None:
                # RI-09: la autorización exitosa queda registrada en la bitácora.
                self._bitacora.registrar_autorizacion(registro.mac, alias=registro.alias)
        self._refrescar()   # El dispositivo autorizado desaparece de la tabla.

    def _aislar(self, mac: str, perfil: PerfilDispositivo) -> None:
        # Única vía de aislamiento: acción explícita del usuario + confirmación.
        if not self._vista.confirmar_aislamiento(perfil):
            return
        # Se ejecuta fuera del hilo de la interfaz; el resultado llega por señal.
        if not self._ejecutor.solicitar(AISLAR, mac, _ACTOR, contexto=self):
            self._vista.advertir("Operación en curso",
                                 f"Ya hay una operación de aislamiento o desbloqueo en curso "
                                 f"para {mac}. Espere a que termine.")

    def _operacion_terminada(self, mac: str, tipo: str, contexto, _resultado) -> None:
        if contexto is self and tipo == AISLAR:
            self._vista.informar("Contención confirmada", texto_contencion_confirmada(mac))
        self._refrescar()   # Un dispositivo aislado o desbloqueado cambia la tabla.

    def _operacion_fallida(self, mac: str, tipo: str, contexto, error) -> None:
        if contexto is self:
            # En cualquier fallo el dispositivo NO se marca como aislado y sigue
            # visible en la tabla.
            self._vista.advertir(titulo_error_aislamiento(error), str(error))

    def _refrescar(self) -> None:
        """Recalcula la tabla con el estado confirmado por los repositorios."""
        if not self._monitoreo.activo:
            return
        try:
            self._publicar(self._servicio_monitoreo.reclasificar())
        except Exception as error:  # noqa: BLE001
            self._vista.advertir("Dispositivos", f"No se pudo actualizar la tabla: {error}")
