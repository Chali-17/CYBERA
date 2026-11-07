"""Pruebas de la transmisión BENIGNA de ARP (Windows/Scapy/Npcap).

Las unitarias inyectan un emisor doble: NO envían tráfico real. Prueban los
cuatro resultados honestos (éxito, fallo, cancelación, desconocido) y que el
motor integra el resultado sin habilitar el aislamiento.

La prueba de transmisión REAL (solicitud ARP estándar al gateway, sin suplantar)
está desactivada salvo ``CYBERA_PRUEBA_RED=1``, porque envía una trama. Debe
usarse en un laboratorio controlado.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from infrastructure.interfaces import OperacionNoEjecutadaError
from infrastructure.network.transmision_arp import (EstadoTransmision, probar_transmision_arp,
                                                    probar_transmision_async)
from infrastructure.network.windows_isolation import WindowsIsolationEngine

OBJETIVO = "192.168.1.1"
INTERFAZ = "192.168.1.8"
MAC = "aa:bb:cc:dd:ee:ff"


def _emisor_responde(mac=MAC):
    llamadas = []

    def emisor(ip_objetivo, ip_interfaz, timeout, cancelar=None):
        llamadas.append((ip_objetivo, ip_interfaz, timeout))
        return mac

    emisor.llamadas = llamadas
    return emisor


# --- Los cuatro resultados honestos -------------------------------------------

def test_exito_cuando_hay_respuesta():
    r = probar_transmision_arp(OBJETIVO, INTERFAZ, emisor=_emisor_responde())
    assert r.estado is EstadoTransmision.EXITO and r.exito
    assert r.mac_resuelta == MAC and OBJETIVO in r.detalle


def test_desconocido_cuando_no_hay_respuesta():
    # Transmitió sin error, pero nadie respondió: sin evidencia de ida y vuelta.
    r = probar_transmision_arp(OBJETIVO, INTERFAZ, emisor=lambda *a, **k: None)
    assert r.estado is EstadoTransmision.DESCONOCIDO and not r.exito
    assert r.mac_resuelta is None


def test_fallo_cuando_el_emisor_lanza():
    def emisor(*a, **k):
        raise RuntimeError("Npcap rechazó el envío")

    r = probar_transmision_arp(OBJETIVO, INTERFAZ, emisor=emisor)
    assert r.estado is EstadoTransmision.FALLO and not r.exito
    assert "Npcap rechazó el envío" in r.detalle


def test_resultado_incluye_duracion_verificable():
    r = probar_transmision_arp(OBJETIVO, INTERFAZ, emisor=_emisor_responde())
    assert isinstance(r.duracion_s, float) and r.duracion_s >= 0.0


def test_cancelado_antes_de_transmitir():
    cancelar = threading.Event()
    cancelar.set()
    emisor = _emisor_responde()
    r = probar_transmision_arp(OBJETIVO, INTERFAZ, cancelar=cancelar, emisor=emisor)
    assert r.estado is EstadoTransmision.CANCELADO
    assert emisor.llamadas == []          # No se envió nada.


def test_cancelado_durante_la_transmision():
    cancelar = threading.Event()

    def emisor(ip, iface, timeout, c):
        c.set()                           # Se cancela mientras se transmite.
        return MAC

    r = probar_transmision_arp(OBJETIVO, INTERFAZ, cancelar=cancelar, emisor=emisor)
    assert r.estado is EstadoTransmision.CANCELADO


# --- Ejecución asíncrona, cancelación fiable y recuperación de recursos --------

def test_async_exito_y_el_hilo_termina():
    trabajo = probar_transmision_async(OBJETIVO, INTERFAZ, emisor=_emisor_responde())
    r = trabajo.esperar(5)
    assert r is not None and r.exito
    assert trabajo.hecho()                         # Recurso recuperado: hilo terminado.
    assert trabajo.resultado is r


def test_async_fallo_deja_resultado_y_termina():
    def emisor(*a, **k):
        raise OSError("sin permiso")

    trabajo = probar_transmision_async(OBJETIVO, INTERFAZ, emisor=emisor)
    r = trabajo.esperar(5)
    assert r.estado is EstadoTransmision.FALLO     # Nunca propaga la excepción.
    assert trabajo.hecho()


def test_async_cancelacion_fiable_es_pronta():
    # Emisor cooperativo que espera a la cancelación (simula un envío largo).
    entro = threading.Event()

    def emisor(ip, iface, timeout, cancelar):
        entro.set()
        assert cancelar.wait(5)                    # Se desbloquea al cancelar.
        return None                                # Devuelve None por cancelación.

    inicio = time.monotonic()
    trabajo = probar_transmision_async(OBJETIVO, INTERFAZ, timeout=30, emisor=emisor)
    assert entro.wait(5)
    trabajo.cancelar()
    r = trabajo.esperar(5)
    assert r.estado is EstadoTransmision.CANCELADO
    assert time.monotonic() - inicio < 5           # No esperó los 30 s del timeout.
    assert trabajo.hecho()


def test_async_callback_recibe_el_resultado():
    recibidos = []
    trabajo = probar_transmision_async(OBJETIVO, INTERFAZ, emisor=_emisor_responde(),
                                       al_terminar=recibidos.append)
    r = trabajo.esperar(5)
    assert recibidos == [r] and r.exito


def test_async_callback_que_falla_no_tumba_el_hilo():
    def callback(_r):
        raise RuntimeError("fallo en el callback")

    trabajo = probar_transmision_async(OBJETIVO, INTERFAZ, emisor=_emisor_responde(),
                                       al_terminar=callback)
    assert trabajo.esperar(5).exito                # El resultado se fijó igualmente.
    assert trabajo.hecho()                         # El hilo terminó pese al callback.


# --- Integración con el motor (sin habilitar el aislamiento) -------------------

def test_motor_registra_el_resultado_sin_habilitar_aislamiento():
    motor = WindowsIsolationEngine()
    assert motor.ultima_transmision is None
    r = motor.probar_transmision(OBJETIVO, INTERFAZ, emisor=_emisor_responde())
    assert r.exito and motor.ultima_transmision is r
    # Transmitir NO equivale a contener: el motor sigue no disponible.
    assert motor.disponible() is False
    with pytest.raises(OperacionNoEjecutadaError):
        motor.isolate("50:9A:4C:4C:78:B2")


def test_motor_propaga_fallo_de_transmision():
    motor = WindowsIsolationEngine()
    r = motor.probar_transmision(OBJETIVO, INTERFAZ,
                                 emisor=lambda *a, **k: (_ for _ in ()).throw(OSError("sin permiso")))
    assert r.estado is EstadoTransmision.FALLO
    assert motor.disponible() is False


def test_motor_async_registra_el_resultado_al_terminar():
    motor = WindowsIsolationEngine()
    trabajo = motor.probar_transmision_async(OBJETIVO, INTERFAZ, emisor=_emisor_responde())
    r = trabajo.esperar(5)
    assert r.exito and motor.ultima_transmision is r
    assert motor.disponible() is False             # Sigue sin habilitar aislamiento.
    with pytest.raises(OperacionNoEjecutadaError):
        motor.isolate("50:9A:4C:4C:78:B2")


# --- Transmisión REAL (laboratorio; desactivada por defecto) -------------------

@pytest.mark.skipif(os.environ.get("CYBERA_PRUEBA_RED") != "1",
                    reason="Transmisión real desactivada (defina CYBERA_PRUEBA_RED=1).")
def test_transmision_real_al_gateway():
    from infrastructure.network.windows_interfaces import WindowsNetworkInterfaceProvider
    activa = next((i for i in WindowsNetworkInterfaceProvider().list_interfaces()
                   if i.conectada and i.ipv4 and i.puerta_enlace), None)
    assert activa is not None, "No hay interfaz conectada con gateway."
    motor = WindowsIsolationEngine()
    # Solicitud ARP estándar al gateway: benigna, no suplantada, no disruptiva.
    r = motor.probar_transmision(activa.puerta_enlace, activa.ipv4, timeout=2.0)
    print(f"\nTransmision real a {activa.puerta_enlace}: {r.estado.value} - {r.detalle} "
          f"(mac={r.mac_resuelta})")
    assert r.estado in (EstadoTransmision.EXITO, EstadoTransmision.DESCONOCIDO,
                        EstadoTransmision.FALLO)
    # El motor NO queda habilitado aunque la transmisión funcione.
    assert motor.disponible() is False
