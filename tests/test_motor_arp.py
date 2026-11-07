"""Pruebas del motor de aislamiento por envenenamiento ARP (agujero negro).

Las unitarias inyectan un emisor y un resolutor ARP DOBLES: NO envían tráfico
real ni suplantan direcciones en la red. Verifican el contrato
``INetworkIsolation``, la construcción de las tramas de agujero negro, la
restauración con las direcciones legítimas y el comportamiento idempotente.

La prueba de envenenamiento REAL está desactivada salvo ``CYBERA_PRUEBA_RED=1``,
porque interrumpe la conectividad de un dispositivo: solo en laboratorio
autorizado.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

import infrastructure.network.arp_spoofing as arp
from infrastructure.interfaces import (EstadoContencion, INetworkIsolation,
                                       OperacionNoEjecutadaError)
from infrastructure.network.arp_spoofing import (ArpSpoofingIsolationEngine,
                                                 DatosRed, ErrorEntornoAislamiento,
                                                 _tramas_envenenamiento,
                                                 _tramas_restauracion)

MAC_OBJ = "AA:BB:CC:DD:EE:01"
IP_OBJ = "10.0.0.50"
DATOS = DatosRed(ip_interfaz="10.0.0.5", mac_interfaz="02:00:00:00:00:05",
                 ip_gateway="10.0.0.1")
MAC_GW_REAL = "02:00:00:00:00:11"
MAC_OBJ_REAL = "AA:BB:CC:DD:EE:01"


def _interfaz():
    return SimpleNamespace(conectada=True, ipv4=DATOS.ip_interfaz, prefijo=24,
                           puerta_enlace=DATOS.ip_gateway, mac=DATOS.mac_interfaz,
                           utilizable=True, nombre="Wi-Fi")


class _ProveedorFalso:
    def list_interfaces(self):
        return [_interfaz()]


def _emisor_registrador():
    tramas = []

    def emisor(trama, iface):
        tramas.append(trama)

    emisor.tramas = tramas
    return emisor


def _resolutor(mapa):
    def resolver(ip, iface):
        return mapa.get(ip)

    return resolver


def _motor(*, ip_mapa=None, emisor=None, resolutor=None):
    """Motor con entorno forzado (sin exigir admin/Npcap) e IP conocida."""
    mapa = {IP_OBJ: MAC_OBJ, DATOS.ip_gateway: MAC_GW_REAL}
    mapa.update(ip_mapa or {})
    motor = ArpSpoofingIsolationEngine(
        proveedor_interfaces=_ProveedorFalso(),
        emisor=emisor or _emisor_registrador(),
        resolutor=resolutor or _resolutor(mapa),
        intervalo=0.05)
    # Se salta la comprobación de entorno real inyectando los datos ya resueltos.
    motor._datos = DATOS
    motor._iface = object()
    motor._ip_objetivo = lambda datos, mac: IP_OBJ    # IP conocida del objetivo.
    return motor


# --- Construcción de tramas ----------------------------------------------------

def test_tramas_de_envenenamiento_cubren_objetivo_y_gateway():
    tramas = _tramas_envenenamiento(DATOS, MAC_OBJ, IP_OBJ)
    assert len(tramas) >= 3
    from scapy.layers.l2 import Ether, ARP
    paquetes = [Ether(t) / ARP(t[14:]) for t in tramas]
    # Al OBJETIVO: la IP del gateway con nuestra MAC.
    al_objetivo = [p for p in paquetes if p[ARP].psrc == DATOS.ip_gateway]
    assert al_objetivo
    assert all(p[ARP].hwsrc.lower() == DATOS.mac_interfaz.lower() for p in al_objetivo)
    # Al GATEWAY: la IP del objetivo con nuestra MAC.
    al_gateway = [p for p in paquetes if p[ARP].psrc == IP_OBJ]
    assert al_gateway
    assert all(p[ARP].hwsrc.lower() == DATOS.mac_interfaz.lower() for p in al_gateway)


def test_tramas_de_restauracion_usan_direcciones_legitimas():
    tramas = _tramas_restauracion(DATOS, MAC_OBJ, IP_OBJ, MAC_GW_REAL, MAC_OBJ_REAL)
    assert tramas, "debe haber al menos una trama de restauración"
    from scapy.layers.l2 import Ether, ARP
    # Ninguna trama de restauración usa nuestra MAC como origen suplantado.
    for t in tramas:
        paquete = Ether(t) / ARP(t[14:])
        assert paquete[ARP].hwsrc.lower() != DATOS.mac_interfaz.lower()


# --- Contrato ------------------------------------------------------------------

def test_cumple_la_interfaz():
    assert isinstance(ArpSpoofingIsolationEngine(proveedor_interfaces=_ProveedorFalso()),
                      INetworkIsolation)


def test_el_error_de_entorno_es_no_ejecutado():
    # El motor garantiza que no tocó la red: fallo CONOCIDO, no recuperación.
    assert issubclass(ErrorEntornoAislamiento, OperacionNoEjecutadaError)


def test_cumple_el_contrato_de_estado_inicial():
    motor = _motor()
    assert motor.status(MAC_OBJ) is EstadoContencion.DESCONOCIDO


def test_isolate_inicia_envio_y_status_confirma():
    emisor = _emisor_registrador()
    motor = _motor(emisor=emisor)
    motor.isolate(MAC_OBJ)
    # Espera a que el hilo envíe al menos una trama.
    for _ in range(50):
        if motor.status(MAC_OBJ) is EstadoContencion.CONTENCION_APLICADA:
            break
        time.sleep(0.02)
    assert motor.status(MAC_OBJ) is EstadoContencion.CONTENCION_APLICADA
    assert emisor.tramas, "el envenenamiento debe haber transmitido tramas"
    motor.release(MAC_OBJ)


def test_isolate_es_idempotente():
    emisor = _emisor_registrador()
    motor = _motor(emisor=emisor)
    motor.isolate(MAC_OBJ)
    motor.isolate(MAC_OBJ)          # No debe crear un segundo bucle.
    time.sleep(0.15)
    assert len(motor._envenenamientos) == 1
    motor.release(MAC_OBJ)


def test_release_detiene_el_envio_y_restaura():
    emisor = _emisor_registrador()
    # Alcance L2 OK (el objetivo responde con su MAC), pero el gateway no se
    # resuelve → la restauración no es verificable.
    motor = _motor(emisor=emisor, resolutor=_resolutor({IP_OBJ: MAC_OBJ}))
    motor.isolate(MAC_OBJ)
    time.sleep(0.15)
    n_antes = len(emisor.tramas)
    motor.release(MAC_OBJ)
    # Sin resolución completa de los pares reales no puede afirmar SIN_CONTENCION.
    assert motor.status(MAC_OBJ) is EstadoContencion.DESCONOCIDO
    assert motor._envenenamientos == {}
    time.sleep(0.15)
    # Dejó de enviar envenenamiento tras el release.
    assert len(emisor.tramas) <= n_antes + 2


def test_release_con_restauracion_verificable_afirma_sin_contencion():
    emisor = _emisor_registrador()
    motor = _motor(emisor=emisor, resolutor=_resolutor({IP_OBJ: MAC_OBJ_REAL,
                                                        DATOS.ip_gateway: MAC_GW_REAL}))
    motor.isolate(MAC_OBJ)
    time.sleep(0.1)
    motor.release(MAC_OBJ)
    # Restauró con las direcciones legítimas: puede afirmar que no aplica contención.
    assert motor.status(MAC_OBJ) is EstadoContencion.SIN_CONTENCION


def test_release_es_idempotente_sin_bucle_previo():
    motor = _motor()
    motor.release(MAC_OBJ)          # No debe lanzar.
    assert motor.status(MAC_OBJ) is EstadoContencion.DESCONOCIDO


def test_isolate_falla_sin_ip_conocida():
    motor = _motor()
    motor._ip_objetivo = lambda datos, mac: None
    with pytest.raises(ErrorEntornoAislamiento):
        motor.isolate(MAC_OBJ)


def test_isolate_falla_si_el_objetivo_no_esta_en_el_mismo_dominio_l2():
    # El objetivo no responde a ARP directo (respuesta de otra MAC o ninguna):
    # probable AP isolation. Debe fallar ANTES de enviar nada.
    emisor = _emisor_registrador()
    motor = _motor(emisor=emisor, resolutor=lambda ip, iface: "02:00:00:00:00:99")
    with pytest.raises(ErrorEntornoAislamiento, match="aísle a los clientes"):
        motor.isolate(MAC_OBJ)
    assert emisor.tramas == []          # No se envió ninguna trama.


# --- Disponibilidad ------------------------------------------------------------

def test_disponible_false_por_motivo_de_entorno(monkeypatch):
    motor = ArpSpoofingIsolationEngine(proveedor_interfaces=_ProveedorFalso())
    monkeypatch.setattr(arp, "platform", SimpleNamespace(system=lambda: "Linux"))
    assert motor.disponible() is False
    assert "Windows" in motor.motivo_no_disponible


# --- Envenenamiento REAL (laboratorio; desactivada por defecto) -----------------

@pytest.mark.skipif(os.environ.get("CYBERA_PRUEBA_RED") != "1",
                    reason="Envenenamiento real desactivado (defina CYBERA_PRUEBA_RED=1).")
def test_envenenamiento_real_y_restauracion():
    motor = ArpSpoofingIsolationEngine()
    assert motor.disponible(), motor.motivo_no_disponible
    ip = os.environ["CYBERA_OBJETIVO_IP"]
    import infrastructure.network.arp_spoofing as mod
    from app.services.inventario_compartido import publicar
    from app.models.dispositivo import PerfilDispositivo
    mac = os.environ["CYBERA_OBJETIVO_MAC"]
    publicar([PerfilDispositivo(mac=mac, ip=ip)])
    assert mod is arp
    motor.isolate(mac)
    time.sleep(2)
    assert motor.status(mac) is EstadoContencion.CONTENCION_APLICADA
    motor.release(mac)
    assert motor.status(mac) is EstadoContencion.DESCONOCIDO
