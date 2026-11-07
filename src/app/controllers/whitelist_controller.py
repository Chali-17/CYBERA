"""WhitelistController: coordina la vista Lista blanca con los servicios.

Reutiliza WhitelistService (fuente de verdad persistente), MonitoringService
(datos en vivo del equipo si está detectado) e IsolationService (acción Aislar).
No mantiene ninguna copia propia de la lista blanca.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.controllers.ejecutor_aislamiento import AISLAR, EjecutorAislamiento
from app.controllers.mensajes_aislamiento import (texto_contencion_confirmada,
                                                  titulo_error_aislamiento)
from app.models.dispositivo import PerfilDispositivo
from app.services.isolation_service import IsolationService
from app.services.monitoring_service import MonitoringService
from app.services.whitelist_service import WhitelistService
from presentation.views.edit_whitelist_dialog import (ACCION_AISLAR, ACCION_ELIMINAR,
                                                      ACCION_GUARDAR, DatosEdicion)
from presentation import formato

_ACTOR = "administrador local"


class WhitelistController(QObject):
    irADispositivos = Signal()

    def __init__(self, vista, lista_blanca: WhitelistService, monitoreo: MonitoringService,
                 aislamiento: IsolationService, parent: QObject | None = None,
                 ejecutor: EjecutorAislamiento | None = None) -> None:
        super().__init__(parent)
        self._vista = vista
        self._lista_blanca = lista_blanca
        self._monitoreo = monitoreo
        self._aislamiento = aislamiento
        self._ejecutor = ejecutor or EjecutorAislamiento(aislamiento, asincrono=False, parent=self)
        self._ejecutor.terminada.connect(self._operacion_terminada)
        self._ejecutor.fallida.connect(self._operacion_fallida)
        vista.mostrada.connect(self.recargar)
        vista.agregarSolicitado.connect(self.irADispositivos.emit)
        vista.editarSolicitado.connect(self._editar)

    def recargar(self) -> None:
        """Carga la tabla desde el repositorio persistente (fuente de verdad)."""
        try:
            registros = self._lista_blanca.listar()
        except Exception as error:  # noqa: BLE001 - p. ej. archivo dañado
            self._vista.mostrar_mensaje(
                f"No se pudo leer la lista blanca: {error}", error=True)
            return
        self._vista.mostrar_dispositivos(registros)

    def _perfil_en_vivo(self, mac: str) -> PerfilDispositivo | None:
        try:
            return self._monitoreo.perfil_detectado(mac)
        except Exception:  # noqa: BLE001 - los datos en vivo son opcionales
            return None

    def _editar(self, mac: str) -> None:
        registro = self._lista_blanca.buscar(mac)
        if registro is None:
            self._vista.advertir("Editar dispositivo",
                                 "El dispositivo ya no está en la lista blanca.")
            self.recargar()
            return
        perfil = self._perfil_en_vivo(mac)
        datos = DatosEdicion(
            mac=registro.mac,
            alias=registro.alias,
            fecha_autorizacion=(registro.fecha_autorizacion.strftime("%d/%m/%Y %H:%M:%S")
                                if registro.fecha_autorizacion else formato.NO_DISPONIBLE),
            ip=perfil.ip if perfil else None,
            fabricante=formato.texto_fabricante(perfil) if perfil else None,
            hostname=perfil.hostname if perfil else None,
            aislado=self._esta_aislado(mac),
            estado_aislamiento=self._texto_aislamiento(mac),
        )
        accion, alias = self._vista.solicitar_edicion(datos)
        if accion == ACCION_GUARDAR:
            self._guardar_alias(registro, alias)
        elif accion == ACCION_ELIMINAR:
            self._eliminar(registro)
        elif accion == ACCION_AISLAR:
            self._aislar(registro, datos.ip)

    def _esta_aislado(self, mac: str) -> bool:
        try:
            return mac in self._aislamiento.macs_aisladas()
        except Exception:  # noqa: BLE001
            return False

    def _texto_aislamiento(self, mac: str) -> str:
        try:
            return formato.texto_situacion_aislamiento(self._aislamiento.situacion(mac))
        except Exception:  # noqa: BLE001 - p. ej. aislamientos.json dañado
            return formato.NO_DISPONIBLE

    def _guardar_alias(self, registro, alias: str | None) -> None:
        if alias == registro.alias:
            return
        try:
            self._lista_blanca.editar_alias(registro.mac, alias)
        except Exception as error:  # noqa: BLE001 - conserva el estado anterior
            self._vista.advertir("No se pudo guardar", str(error))
            self.recargar()
            return
        self._vista.informar("Alias actualizado",
                             f"El alias de {registro.mac} se guardó correctamente.")
        self.recargar()

    def _eliminar(self, registro) -> None:
        alias = registro.alias or "sin alias"
        if not self._vista.confirmar_eliminacion(alias, registro.mac):
            return
        try:
            self._lista_blanca.retirar(registro.mac)
        except Exception as error:  # noqa: BLE001 - conserva el registro visible
            self._vista.advertir("No se pudo eliminar", str(error))
            self.recargar()
            return
        self._vista.informar("Autorización eliminada",
                             f"«{alias}» ({registro.mac}) ya no está en la lista blanca.")
        self.recargar()

    def _aislar(self, registro, ip: str | None) -> None:
        alias = registro.alias or "sin alias"
        if not self._vista.confirmar_aislamiento(alias, registro.mac, ip):
            return
        if not self._ejecutor.solicitar(AISLAR, registro.mac, _ACTOR, contexto=self):
            self._vista.advertir("Operación en curso",
                                 f"Ya hay una operación de aislamiento o desbloqueo en curso "
                                 f"para {registro.mac}. Espere a que termine.")

    def _operacion_terminada(self, mac: str, tipo: str, contexto, _resultado) -> None:
        if contexto is not self:
            return
        self._vista.informar("Contención confirmada", texto_contencion_confirmada(mac))
        self.recargar()

    def _operacion_fallida(self, mac: str, tipo: str, contexto, error) -> None:
        if contexto is self:
            # Incluye RI-05: un dispositivo autorizado no puede aislarse.
            self._vista.advertir(titulo_error_aislamiento(error), str(error))
