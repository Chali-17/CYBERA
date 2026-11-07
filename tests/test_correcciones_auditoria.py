"""Pruebas de regresión de la auditoría de la máquina de estados (H1–H8 y brechas).

Todas usan un MOTOR SIMULADO o ningún motor. No demuestran que una red real
quede aislada: el motor físico no está implementado en esta fase.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
from datetime import datetime
from pathlib import Path

import pytest

from app.controllers.device_controller import texto_contencion_confirmada, titulo_error_aislamiento
from app.models.aislamiento import AccionAislamiento, EstadoAislamiento
from app.models.dispositivo_confiable import DispositivoConfiable, OrigenRegistro
from app.models.operacion_aislamiento import (MOTIVOS_FALLO_CONOCIDO, MOTIVOS_INCIERTOS,
                                              EstadoOperacion, MotivoFallo, OperacionAislamiento,
                                              TipoOperacion)
from app.services.isolation_service import (AislamientoFallidoError, AislamientoNoDisponibleError,
                                            DesbloqueoFallidoError, DispositivoProtegidoError,
                                            IsolationService, OperacionEnCursoError,
                                            RegistroAislamientoError, SituacionAislamiento,
                                            VerificacionContencion)
from app.services.reservas_mac import ReservasPorMac
from app.services.whitelist_service import AutorizacionBloqueadaError, WhitelistService
from dobles import MotorSimulado
from infrastructure.instancia_unica import InstanciaUnica, ResultadoBloqueo
from infrastructure.interfaces import EstadoContencion, IIsolationRepository
from infrastructure.persistence import json_file
from infrastructure.persistence.isolation_repository import IncoherenciaError, JsonIsolationRepository
from infrastructure.persistence.json_file import ArchivoDatosError
from infrastructure.persistence.whitelist_repository import JsonWhitelistRepository
from presentation import formato

RAIZ = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 21, 9, 0, 0)
MAC = "50:9A:4C:4C:78:B2"
MAC_2 = "AC:00:00:00:00:30"
ACTOR = "administrador local"


class Entorno:
    """Servicios reales sobre archivos temporales, con reserva por MAC compartida
    entre lista blanca y aislamiento (como en app/main.py)."""

    def __init__(self, carpeta: Path, motor=None):
        self.carpeta = carpeta
        self.ruta = carpeta / "aislamientos.json"
        self.repo = JsonIsolationRepository(self.ruta)
        self.repo_lb = JsonWhitelistRepository(carpeta / "lista_blanca.json")
        self.reservas = ReservasPorMac()
        self.motor = motor
        self.lb = WhitelistService(self.repo_lb, reloj=lambda: T0, reservas=self.reservas)
        self.servicio = IsolationService(self.repo, self.repo_lb, motor=motor, reloj=lambda: T0,
                                         reservas=self.reservas)

    def reiniciar(self, motor=None) -> "Entorno":
        """Nueva «ejecución» sobre la misma carpeta (memoria vacía)."""
        return Entorno(self.carpeta, motor)

    def estados(self, mac=MAC):
        return [(o.tipo.value, o.estado.value, o.motivo_fallo.value if o.motivo_fallo else None)
                for o in self.repo.operaciones(mac)]

    def texto(self, mac=MAC):
        return formato.texto_situacion_aislamiento(self.servicio.situacion(mac))


@pytest.fixture
def e(tmp_path):
    return Entorno(tmp_path, MotorSimulado())


def _en_hilo(funcion, *args):
    resultado = {}

    def ejecutar():
        try:
            resultado["valor"] = funcion(*args)
        except BaseException as error:  # noqa: BLE001
            resultado["error"] = error

    hilo = threading.Thread(target=ejecutar, daemon=True)
    hilo.start()
    return hilo, resultado


def _fallar_escrituras(monkeypatch, desde: int):
    original = json_file.os.replace
    cuenta = {"n": 0}

    def replace(origen, destino):
        cuenta["n"] += 1
        if cuenta["n"] >= desde:
            raise PermissionError("disco protegido contra escritura")
        return original(origen, destino)

    monkeypatch.setattr(json_file.os, "replace", replace)


# =============================================================================
# H1 — Lista blanca y aislamiento coordinados
# =============================================================================

def test_h1_autorizar_durante_un_aislamiento_se_rechaza(e):
    liberar = e.motor.bloquear(MAC)
    hilo, resultado = _en_hilo(e.servicio.aislar, MAC, ACTOR)
    assert e.motor.dentro[MAC].wait(5)
    with pytest.raises(AutorizacionBloqueadaError):
        e.lb.autorizar(MAC, "PC")                      # Carrera de la auditoría (H1)
    liberar.set()
    hilo.join(5)
    assert "error" not in resultado
    assert not e.repo_lb.exists(MAC)                   # La autorización no se completó
    assert e.servicio.macs_aisladas() == {MAC}


def test_h1_aislar_durante_una_autorizacion_se_rechaza(e, monkeypatch):
    dentro, seguir = threading.Event(), threading.Event()
    original = e.repo_lb.add

    def add_lento(dispositivo):
        dentro.set()
        assert seguir.wait(5)
        original(dispositivo)

    monkeypatch.setattr(e.repo_lb, "add", add_lento)
    hilo, resultado = _en_hilo(e.lb.autorizar, MAC, "PC")
    assert dentro.wait(5)
    with pytest.raises(OperacionEnCursoError, match="autorización"):
        e.servicio.aislar(MAC, ACTOR)
    seguir.set()
    hilo.join(5)
    assert "error" not in resultado and e.repo_lb.exists(MAC)
    assert e.motor.llamadas == [] and not e.ruta.exists()


def test_h1_carrera_autorizar_contra_aislar_nunca_deja_ambos(tmp_path):
    for vuelta in range(25):
        ent = Entorno(tmp_path / str(vuelta), MotorSimulado())
        barrera = threading.Barrier(2)

        def autorizar():
            barrera.wait()
            try:
                ent.lb.autorizar(MAC, "PC")
            except AutorizacionBloqueadaError:
                pass

        def aislar():
            barrera.wait()
            try:
                ent.servicio.aislar(MAC, ACTOR)
            except (OperacionEnCursoError, DispositivoProtegidoError):
                pass

        hilos = [threading.Thread(target=autorizar), threading.Thread(target=aislar)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(5)
        autorizada = ent.repo_lb.exists(MAC)
        aislada = MAC in ent.servicio.macs_aisladas()
        assert not (autorizada and aislada), f"vuelta {vuelta}: autorizada y aislada"
        assert autorizada or aislada


def _autorizar_por_fuera(ent):
    """Cambio de la lista blanca que NO pasa por WhitelistService (sin reserva)."""
    ent.repo_lb.add(DispositivoConfiable(MAC, "PC", T0, OrigenRegistro.MANUAL, True))


def test_h1_revalida_antes_de_invocar_al_motor(e, monkeypatch):
    original = e.repo.registrar_solicitud

    def registrar(op):
        original(op)
        _autorizar_por_fuera(e)                        # Justo tras guardar REQUESTED

    monkeypatch.setattr(e.repo, "registrar_solicitud", registrar)
    with pytest.raises(DispositivoProtegidoError) as error:
        e.servicio.aislar(MAC, ACTOR)
    assert error.value.operacion.motivo_fallo is MotivoFallo.AUTORIZADA
    assert e.motor.llamadas == []                      # Nada se envió al motor
    assert e.estados() == [("AISLAR", "FAILED", "AUTORIZADA")]
    assert e.servicio.macs_aisladas() == set()


def test_h1_revalida_antes_de_confirmar_y_revierte(e, monkeypatch):
    original = e.motor.isolate

    def isolate(mac):
        original(mac)
        _autorizar_por_fuera(e)                        # Autorizada mientras el motor actuaba

    monkeypatch.setattr(e.motor, "isolate", isolate)
    with pytest.raises(DispositivoProtegidoError, match="se revirtió"):
        e.servicio.aislar(MAC, ACTOR)
    assert e.motor.llamadas == [("isolate", MAC), ("release", MAC)]   # Reversión
    assert e.servicio.macs_aisladas() == set()
    assert e.estados() == [("AISLAR", "FAILED", "AUTORIZADA")]
    assert e.texto() == "Sin contención según el motor (verificado a las 09:00:00)"


def test_h1_reversion_no_verificada_queda_como_desconocida(e, monkeypatch):
    original = e.motor.isolate

    def isolate(mac):
        original(mac)
        _autorizar_por_fuera(e)
        e.motor.falla_release = True                   # La reversión también falla

    monkeypatch.setattr(e.motor, "isolate", isolate)
    with pytest.raises(DispositivoProtegidoError, match="requiere recuperación") as error:
        e.servicio.aislar(MAC, ACTOR)
    assert error.value.requiere_recuperacion
    assert e.servicio.macs_aisladas() == set()
    # Estado explícito y evidencia conservada (L2).
    assert e.estados() == [("AISLAR", "UNCERTAIN", "REVERSION_FALLIDA")]
    assert "Reversión fallida" in e.repo.operaciones(MAC)[0].detalle
    assert e.servicio.requiere_recuperacion(MAC)
    assert e.texto() == ("Requiere recuperación: resultado incierto del último aislamiento "
                         "(el motor informó DESCONOCIDO a las 09:00:00)")


def test_h1_lista_blanca_ilegible_al_revalidar_no_continua(e, monkeypatch):
    llamadas = {"n": 0}
    original = e.repo_lb.exists

    def exists(mac):
        llamadas["n"] += 1
        if llamadas["n"] >= 2:                         # Falla en la revalidación
            raise ArchivoDatosError("lista_blanca.json dañado")
        return original(mac)

    monkeypatch.setattr(e.repo_lb, "exists", exists)
    with pytest.raises(DispositivoProtegidoError):
        e.servicio.aislar(MAC, ACTOR)
    assert e.motor.llamadas == []
    assert e.estados() == [("AISLAR", "FAILED", "AUTORIZACION_NO_VERIFICABLE")]


def test_h1_main_comparte_la_reserva_entre_servicios(qapp, tmp_path):
    from app.main import construir
    aplicacion = construir(tmp_path)
    try:
        assert aplicacion.servicio_aislamiento._reservas is \
            aplicacion.servicio_lista_blanca._reservas
    finally:
        aplicacion.monitoreo.detener()
        aplicacion.configuracion.detener()


# =============================================================================
# H3 — Contrato EstadoContencion y reinicio con motor nuevo
# =============================================================================

def test_h3_motor_simulado_devuelve_desconocido_para_mac_desconocida():
    assert MotorSimulado().status(MAC) is EstadoContencion.DESCONOCIDO


def test_h3_reinicio_con_registro_activo_y_motor_sin_estado(e):
    e.servicio.aislar(MAC, ACTOR)
    nuevo = e.reiniciar(MotorSimulado())               # Motor nuevo: no conoce la MAC
    situacion = nuevo.servicio.situacion(MAC)
    assert situacion.registrado and not situacion.aislado_confirmado
    assert nuevo.texto() == "Registrado, estado sin verificar"
    # Antes el desbloqueo se «confirmaba» solo; ahora DESCONOCIDO no confirma nada.
    with pytest.raises(DesbloqueoFallidoError, match="DESCONOCIDO"):
        nuevo.servicio.desbloquear(MAC, ACTOR)
    assert nuevo.servicio.macs_aisladas() == {MAC}
    # DESCONOCIDO tras release: resultado incierto → requiere recuperación (L2).
    assert nuevo.estados()[-1] == ("DESBLOQUEAR", "UNCERTAIN", "SIN_CONFIRMACION")
    assert nuevo.texto() == ("Requiere recuperación: resultado incierto del último desbloqueo "
                             "(el motor informó DESCONOCIDO a las 09:00:00)")


@pytest.mark.parametrize("estado, texto", [
    (EstadoContencion.CONTENCION_APLICADA,
     "Contención aplicada según el motor (verificado a las 09:00:00)"),
    (EstadoContencion.SIN_CONTENCION,
     "Registrado como aislado, pero el motor no aplica contención (verificado a las 09:00:00)"),
    (EstadoContencion.DESCONOCIDO, "Estado sin verificar: el motor no pudo determinarlo"),
])
def test_h3_verificar_registrados_solo_anota_en_memoria(e, estado, texto):
    e.servicio.aislar(MAC, ACTOR)
    previo = e.ruta.read_bytes()
    nuevo = e.reiniciar(MotorSimulado(estado_forzado=estado))
    assert nuevo.texto() == "Registrado, estado sin verificar"
    resultado = nuevo.servicio.verificar_registrados()
    assert resultado[MAC].estado is estado
    assert nuevo.texto() == texto
    assert e.ruta.read_bytes() == previo               # No se modifica el registro


def test_h3_verificar_sin_motor_no_hace_nada(e):
    e.servicio.aislar(MAC, ACTOR)
    nuevo = e.reiniciar(None)
    assert nuevo.servicio.verificar_registrados() == {}
    assert nuevo.texto() == "Registrado, estado sin verificar"


def test_h3_verificar_con_status_que_falla(e):
    e.servicio.aislar(MAC, ACTOR)
    nuevo = e.reiniciar(MotorSimulado(falla_status=True))
    assert nuevo.servicio.verificar_registrados()[MAC].estado is EstadoContencion.DESCONOCIDO


def test_h3_construir_presenta_registros_como_sin_verificar(qapp, tmp_path):
    Entorno(tmp_path, MotorSimulado()).servicio.aislar(MAC, ACTOR)
    from app.main import construir
    aplicacion = construir(tmp_path)                   # Producción: motor=None
    try:
        situacion = aplicacion.servicio_aislamiento.situacion(MAC)
        assert formato.texto_situacion_aislamiento(situacion) == "Registrado, estado sin verificar"
        assert not situacion.aislado_confirmado
    finally:
        aplicacion.monitoreo.detener()
        aplicacion.configuracion.detener()


@pytest.mark.parametrize("valor", [None, True, "SIN_CONTENCION", 0])
def test_h3_valores_fuera_de_contrato_no_confirman_desbloqueo(e, valor):
    e.servicio.aislar(MAC, ACTOR)
    e.motor.estado_forzado = valor if valor is not None else object()
    with pytest.raises(DesbloqueoFallidoError):
        e.servicio.desbloquear(MAC, ACTOR)
    assert e.servicio.macs_aisladas() == {MAC}
    assert e.servicio.verificacion(MAC).estado is EstadoContencion.DESCONOCIDO


def test_h3_desbloqueo_confirmado_no_afirma_conectividad(e):
    e.servicio.aislar(MAC, ACTOR)
    e.servicio.desbloquear(MAC, ACTOR)
    texto = e.texto()
    assert texto == "Sin contención según el motor (verificado a las 09:00:00)"
    assert "conectividad" not in texto.lower() and "restaurad" not in texto.lower()


# =============================================================================
# H2 — Instancia única
# =============================================================================

def test_h2_segunda_instancia_en_el_mismo_proceso(tmp_path):
    primera, segunda = InstanciaUnica(tmp_path), InstanciaUnica(tmp_path)
    assert primera.adquirir() is ResultadoBloqueo.ADQUIRIDO
    try:
        assert segunda.adquirir() is ResultadoBloqueo.OTRA_INSTANCIA
        assert "ya se está ejecutando" in segunda.detalle
    finally:
        primera.liberar()
    assert segunda.adquirir() is ResultadoBloqueo.ADQUIRIDO     # Liberado al cerrar
    segunda.liberar()


def _python(*partes: str, **entorno) -> subprocess.Popen:
    """Ejecuta un proceso Python aparte (otra «instancia»). Cada parte se
    desindenta por separado antes de unirlas."""
    codigo = "\n".join(textwrap.dedent(parte) for parte in partes)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", **entorno}
    return subprocess.Popen([sys.executable, "-c", codigo], cwd=RAIZ, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                            text=True, encoding="utf-8")


_PRELUDIO = """
    import sys; sys.path.insert(0, "src")
    from pathlib import Path
    from infrastructure.instancia_unica import InstanciaUnica
"""


def test_h2_segunda_instancia_en_otro_proceso(tmp_path):
    otro = _python(_PRELUDIO, f"""
    i = InstanciaUnica(Path(r"{tmp_path}"))
    print(i.adquirir().value, flush=True)
    sys.stdin.readline()                     # Mantiene el bloqueo hasta que la prueba siga
    i.liberar()
    """)
    try:
        assert otro.stdout.readline().strip() == "ADQUIRIDO"
        aqui = InstanciaUnica(tmp_path)
        assert aqui.adquirir() is ResultadoBloqueo.OTRA_INSTANCIA
    finally:
        otro.communicate("\n", timeout=20)
    assert aqui.adquirir() is ResultadoBloqueo.ADQUIRIDO
    aqui.liberar()


def test_h2_bloqueo_de_un_proceso_terminado_se_recupera(tmp_path):
    caido = _python(_PRELUDIO, f"""
    import os
    i = InstanciaUnica(Path(r"{tmp_path}"))  # Referencia viva: QLockFile no se destruye
    print(i.adquirir().value, flush=True)
    os._exit(0)                              # Termina sin liberar el bloqueo
    """)
    salida, _ = caido.communicate(timeout=20)
    assert salida.strip() == "ADQUIRIDO" and (tmp_path / "cybera.lock").exists()
    aqui = InstanciaUnica(tmp_path)
    assert aqui.adquirir() is ResultadoBloqueo.ADQUIRIDO
    aqui.liberar()


def test_h2_error_de_carpeta_no_es_otra_instancia(tmp_path):
    archivo = tmp_path / "no_es_carpeta"
    archivo.write_text("x", encoding="utf-8")
    instancia = InstanciaUnica(archivo)                # La «carpeta» es un archivo
    assert instancia.adquirir() is ResultadoBloqueo.ERROR
    assert not instancia.adquirido


_MAIN_CON_AVISOS = """
    import sys; sys.path.insert(0, "src")
    import app.main as m
    avisos = []
    class Caja:
        information = staticmethod(lambda *a: avisos.append(("info", a[2])))
        critical = staticmethod(lambda *a: avisos.append(("critico", a[2])))
    m.QMessageBox = Caja
"""


def test_h2_main_no_arranca_ni_toca_datos_si_hay_otra_instancia(tmp_path):
    lista = tmp_path / "lista_blanca.json"
    lista.write_text('{"version": 1, "dispositivos": []}', encoding="utf-8")
    previo = sorted(p.name for p in tmp_path.iterdir())
    retenedor = InstanciaUnica(tmp_path)
    assert retenedor.adquirir() is ResultadoBloqueo.ADQUIRIDO
    try:
        proceso = _python(_MAIN_CON_AVISOS, """
        def no_construir(*a, **k):
            raise AssertionError("construir() no debe llamarse")
        m.construir = no_construir
        print(m.main(), avisos[0][0], flush=True)
        """, CYBERA_DATOS=str(tmp_path))
        salida, errores = proceso.communicate(timeout=60)
    finally:
        retenedor.liberar()
    assert salida.split() == ["1", "info"], errores
    assert sorted(p.name for p in tmp_path.iterdir()) == previo   # Nada nuevo ni modificado
    assert lista.read_text(encoding="utf-8") == '{"version": 1, "dispositivos": []}'


def test_h2_main_libera_el_bloqueo_si_el_arranque_falla(tmp_path):
    proceso = _python(_MAIN_CON_AVISOS, f"""
    from pathlib import Path
    from infrastructure.instancia_unica import InstanciaUnica
    def falla(*a, **k):
        raise RuntimeError("fallo simulado al construir")
    m.construir = falla
    try:
        m.main()
    except RuntimeError:
        pass
    print(InstanciaUnica(Path(r"{tmp_path}")).adquirir().value, flush=True)
    """, CYBERA_DATOS=str(tmp_path))
    salida, errores = proceso.communicate(timeout=60)
    assert salida.strip() == "ADQUIRIDO", errores


# =============================================================================
# H4 — Interrupciones, fallos de persistencia y mensajes sin verificar
# =============================================================================

def test_h4_desbloqueo_interrumpido_conserva_el_registro(e):
    accion = e.servicio.aislar(MAC, ACTOR)
    e.repo.registrar_solicitud(OperacionAislamiento(
        MAC, TipoOperacion.DESBLOQUEAR, ACTOR, T0, id_aislamiento=accion.id_aislamiento).solicitar())
    nuevo = e.reiniciar(None)
    assert nuevo.texto() == "Desbloqueo solicitado, sin confirmar"
    nuevo.servicio.recuperar_interrumpidas()
    assert nuevo.estados() == [("AISLAR", "CONFIRMED", None),
                               ("DESBLOQUEAR", "UNCERTAIN", "INTERRUMPIDA")]
    assert nuevo.servicio.macs_aisladas() == {MAC}     # Se conserva el registro
    assert nuevo.texto() == "Requiere recuperación: resultado incierto del último desbloqueo"


@pytest.mark.parametrize("operacion", ["aislar", "desbloquear"])
def test_h4_cierre_abrupto_durante_el_motor(e, operacion):
    if operacion == "desbloquear":
        e.servicio.aislar(MAC, ACTOR)
    metodo = "isolate" if operacion == "aislar" else "release"
    original = getattr(e.motor, metodo)

    def muere(mac):
        original(mac)
        raise SystemExit("cierre abrupto")

    setattr(e.motor, metodo, muere)
    with pytest.raises(SystemExit):
        getattr(e.servicio, operacion)(MAC, ACTOR)
    assert e.servicio._reservas.en_curso(MAC) is None   # La reserva se liberó
    assert e.repo.operaciones(MAC)[-1].estado is EstadoOperacion.REQUESTED
    nuevo = e.reiniciar(None)
    nuevo.servicio.recuperar_interrumpidas()
    ultima = nuevo.repo.operaciones(MAC)[-1]
    assert ultima.estado is EstadoOperacion.UNCERTAIN
    assert ultima.motivo_fallo is MotivoFallo.INTERRUMPIDA
    assert ultima.tipo.value == operacion.upper()           # Es la operación interrumpida
    assert nuevo.servicio.requiere_recuperacion(MAC)
    if operacion == "aislar":
        assert nuevo.servicio.macs_aisladas() == set()
        assert nuevo.texto() == "Requiere recuperación: resultado incierto del último aislamiento"
    else:
        assert nuevo.servicio.macs_aisladas() == {MAC}
        assert nuevo.texto() == "Requiere recuperación: resultado incierto del último desbloqueo"


def test_h4_fallo_al_registrar_confirmacion_de_aislamiento(e, monkeypatch):
    _fallar_escrituras(monkeypatch, desde=2)
    with pytest.raises(RegistroAislamientoError, match="podría seguir aplicada") as error:
        e.servicio.aislar(MAC, ACTOR)
    monkeypatch.undo()
    assert titulo_error_aislamiento(error.value) == "Aislamiento sin verificar"
    assert e.servicio.macs_aisladas() == set()
    assert e.texto() == "Aislamiento solicitado, sin confirmar"
    e.servicio.recuperar_interrumpidas()
    # Requiere recuperación; en esta ejecución se muestra además lo que informó el motor.
    assert e.texto() == ("Requiere recuperación: resultado incierto del último aislamiento "
                         "(el motor informó CONTENCION_APLICADA a las 09:00:00)")
    assert e.reiniciar(None).texto() == \
        "Requiere recuperación: resultado incierto del último aislamiento"


def test_h4_fallo_al_registrar_confirmacion_de_desbloqueo(e, monkeypatch):
    e.servicio.aislar(MAC, ACTOR)
    _fallar_escrituras(monkeypatch, desde=2)           # REQUESTED se guarda; el resultado no
    with pytest.raises(RegistroAislamientoError):
        e.servicio.desbloquear(MAC, ACTOR)
    monkeypatch.undo()
    assert e.servicio.macs_aisladas() == {MAC}
    assert e.texto() == "Desbloqueo solicitado, sin confirmar"
    nuevo = e.reiniciar(None)
    nuevo.servicio.recuperar_interrumpidas()
    assert nuevo.texto() == "Requiere recuperación: resultado incierto del último desbloqueo"


def test_h4_fallo_al_registrar_el_propio_fallo(e, monkeypatch):
    e.motor.confirma_aislar = False
    _fallar_escrituras(monkeypatch, desde=2)
    with pytest.raises(AislamientoFallidoError, match="no se pudo registrar el fallo"):
        e.servicio.aislar(MAC, ACTOR)
    monkeypatch.undo()
    assert e.estados() == [("AISLAR", "REQUESTED", None)]
    e.servicio.recuperar_interrumpidas()
    assert e.estados() == [("AISLAR", "UNCERTAIN", "INTERRUMPIDA")]


def test_h4_disponible_que_lanza_es_no_disponible(tmp_path):
    motor = MotorSimulado()
    motor.disponible = lambda: (_ for _ in ()).throw(RuntimeError("sin privilegios"))
    ent = Entorno(tmp_path, motor)
    assert not ent.servicio.disponible
    with pytest.raises(AislamientoNoDisponibleError):
        ent.servicio.aislar(MAC, ACTOR)
    assert motor.llamadas == [] and not ent.ruta.exists()


def _situaciones():
    """Todas las combinaciones relevantes de registro, operación y verificación."""
    accion = AccionAislamiento(mac_objetivo=MAC, fecha_inicio=T0, autorizado_por="u")
    ops = [None]
    for tipo in TipoOperacion:
        base = OperacionAislamiento(MAC, tipo, ACTOR, T0).solicitar()
        ops += [base, base.confirmar(T0, "x")]
        ops += [base.fallar(m, T0) for m in MOTIVOS_FALLO_CONOCIDO]
        ops += [base.marcar_incierta(m, T0) for m in MOTIVOS_INCIERTOS]
    verificaciones = [None] + [VerificacionContencion(e, T0) for e in EstadoContencion]
    for contencion in (None, accion):
        for op in ops:
            for v in verificaciones:
                en_curso = op.tipo if op is not None and op.en_curso else None
                incierta = op is not None and op.requiere_recuperacion
                yield SituacionAislamiento(MAC, contencion, op, en_curso, v,
                                           requiere_recuperacion=incierta,
                                           operacion_incierta=op if incierta else None)


def test_h4_ningun_texto_afirma_aislado_o_no_aislado_como_hecho():
    for situacion in _situaciones():
        texto = formato.texto_situacion_aislamiento(situacion)
        assert not texto.startswith(("Aislado", "No aislado")), texto
        assert "conectividad" not in texto.lower(), texto
        if situacion.requiere_recuperacion and situacion.en_curso is None:
            assert texto.startswith("Requiere recuperación"), texto
        elif (situacion.verificacion is None and situacion.registrado
              and situacion.en_curso is None):
            assert texto == "Registrado, estado sin verificar"


def test_h4_mensaje_de_exito_no_afirma_perdida_de_conectividad():
    texto = texto_contencion_confirmada(MAC)
    assert "aplica contención" in texto and "no es una comprobación independiente" in texto


def test_h4_dialogo_sin_texto_explicito_no_afirma_estado(qapp):
    from presentation.views.edit_whitelist_dialog import DatosEdicion, EditarListaBlancaDialog
    from PySide6.QtWidgets import QLabel
    for aislado, esperado in [(True, "Registrado, estado sin verificar"),
                              (False, "Sin aislamiento registrado")]:
        dialogo = EditarListaBlancaDialog(DatosEdicion(MAC, None, "21/10/2026", aislado=aislado))
        textos = {e.text() for e in dialogo.findChildren(QLabel)}
        assert esperado in textos and "Aislado" not in textos and "No aislado" not in textos


# =============================================================================
# H5 / H6 / H7 / H8 — Integridad de aislamientos.json
# =============================================================================

@pytest.mark.parametrize("version", [True, False, 1.0, "2", None, 3, -1])
def test_h5_version_no_entera_o_desconocida_se_rechaza(e, version):
    contenido = json.dumps({"version": version, "aislamientos": []})
    e.ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(ArchivoDatosError, match="formato desconocido"):
        e.repo.activos()
    with pytest.raises(RegistroAislamientoError):
        e.servicio.aislar(MAC, ACTOR)
    assert e.motor.llamadas == [] and e.ruta.read_text(encoding="utf-8") == contenido


def _v1(*acciones, con_version=True):
    datos = {"aislamientos": [a.a_dict() for a in acciones]}
    if con_version:
        datos = {"version": 1, **datos}
    return json.dumps(datos)


@pytest.mark.parametrize("con_version", [True, False])
def test_h6_migracion_crea_respaldo_exacto(e, con_version):
    contenido = _v1(AccionAislamiento(mac_objetivo=MAC_2, fecha_inicio=T0, autorizado_por="u"),
                    con_version=con_version)
    e.ruta.write_text(contenido, encoding="utf-8")
    e.servicio.aislar(MAC, ACTOR)
    respaldo = e.ruta.with_name("aislamientos.json.v1.bak")
    assert respaldo.read_text(encoding="utf-8") == contenido       # Copia exacta
    assert json.loads(e.ruta.read_text(encoding="utf-8"))["version"] == 2
    assert e.servicio.macs_aisladas() == {MAC, MAC_2}               # Nada se perdió
    e.servicio.desbloquear(MAC, ACTOR)                              # Ya es v2: sin más copias
    assert sorted(p.name for p in e.carpeta.glob("*.bak")) == ["aislamientos.json.v1.bak"]


def test_h6_no_sobrescribe_un_respaldo_previo(e):
    previo = e.ruta.with_name("aislamientos.json.v1.bak")
    previo.write_text("respaldo anterior", encoding="utf-8")
    e.ruta.write_text(_v1(), encoding="utf-8")
    e.servicio.aislar(MAC, ACTOR)
    assert previo.read_text(encoding="utf-8") == "respaldo anterior"
    assert e.ruta.with_name("aislamientos.json.v1.1.bak").read_text(encoding="utf-8") == _v1()


def test_h6_si_el_respaldo_falla_no_se_migra_ni_se_llama_al_motor(e, monkeypatch):
    contenido = _v1()
    e.ruta.write_text(contenido, encoding="utf-8")
    original = Path.open

    def open_sin_respaldo(self, *args, **kwargs):
        if self.name.endswith(".bak"):
            raise PermissionError("sin permiso de escritura")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_sin_respaldo)
    with pytest.raises(RegistroAislamientoError, match="copia de respaldo"):
        e.servicio.aislar(MAC, ACTOR)
    monkeypatch.undo()
    assert e.motor.llamadas == []
    assert e.ruta.read_text(encoding="utf-8") == contenido


def _registro(**cambios):
    base = AccionAislamiento(mac_objetivo=MAC, fecha_inicio=T0, autorizado_por="u",
                             id_aislamiento="A1").a_dict()
    return {**base, **cambios}


def _op(tipo="AISLAR", estado="REQUESTED", **cambios):
    base = {"idOperacion": "O1", "macObjetivo": MAC, "tipo": tipo, "estado": estado,
            "fechaSolicitud": T0.isoformat(), "fechaResolucion": None, "motivoFallo": None,
            "detalle": None, "idAislamiento": None, "solicitadoPor": "u"}
    return {**base, **cambios}


INACTIVO = {"estado": "INACTIVO", "fechaFin": T0.isoformat()}


@pytest.mark.parametrize("aislamientos, operaciones", [
    ([_registro(), _registro(idAislamiento="A2")], []),                       # 2 ACTIVO misma MAC
    ([_registro(), _registro(**INACTIVO)], []),                               # id repetido
    ([], [_op(), _op(idOperacion="O2")]),                                     # 2 REQUESTED
    ([_registro()], [_op()]),                                                 # AISLAR en curso + ACTIVO
    ([], [_op("DESBLOQUEAR", idAislamiento="A1")]),                           # sin su ACTIVO
    ([], [_op(estado="CONFIRMED", fechaResolucion=T0.isoformat(),
              idAislamiento="A1")]),                                          # confirmado sin registro
    ([_registro(fechaFin=T0.isoformat())], []),                               # ACTIVO con fechaFin
    ([_registro(estado="INACTIVO")], []),                                     # INACTIVO sin fechaFin
    ([_registro(**INACTIVO)], [_op(macObjetivo=MAC_2, estado="CONFIRMED",
                                   fechaResolucion=T0.isoformat(), idAislamiento="A1")]),  # otra MAC
    ([_registro()], [_op("DESBLOQUEAR", "CONFIRMED", fechaResolucion=T0.isoformat(),
                         idAislamiento="A1")]),                               # desbloqueado pero ACTIVO
    ([], [_op(), _op(idOperacion="O1", macObjetivo=MAC_2)]),                  # idOperacion repetido
])
def test_h7_registros_contradictorios_se_rechazan_sin_modificar(e, aislamientos, operaciones):
    contenido = json.dumps({"version": 2, "aislamientos": aislamientos, "operaciones": operaciones})
    e.ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(ArchivoDatosError, match="contradictorios"):
        e.repo.operaciones()
    with pytest.raises(RegistroAislamientoError):
        e.servicio.aislar(MAC, ACTOR)
    assert e.motor.llamadas == [] and e.ruta.read_text(encoding="utf-8") == contenido


def test_h7_archivo_coherente_valido_se_lee(e):
    contenido = json.dumps({"version": 2, "aislamientos": [_registro(**INACTIVO)], "operaciones": [
        _op(estado="CONFIRMED", fechaResolucion=T0.isoformat(), idAislamiento="A1"),
        _op("DESBLOQUEAR", "CONFIRMED", idOperacion="O2", fechaResolucion=T0.isoformat(),
            idAislamiento="A1")]})
    e.ruta.write_text(contenido, encoding="utf-8")
    assert len(e.repo.operaciones()) == 2 and e.repo.activos() == []


def test_h7_nunca_se_escribe_un_estado_contradictorio(e):
    e.repo.registrar_solicitud(OperacionAislamiento(MAC, TipoOperacion.AISLAR, ACTOR, T0).solicitar())
    previo = e.ruta.read_bytes()
    with pytest.raises(IncoherenciaError):
        e.repo.crear(AccionAislamiento(mac_objetivo=MAC, fecha_inicio=T0, autorizado_por="u"))
    assert e.ruta.read_bytes() == previo


def test_h8_crear_y_finalizar_fuera_del_contrato():
    abstractos = IIsolationRepository.__abstractmethods__
    assert "crear" not in abstractos and "finalizar" not in abstractos


def test_h8_ningun_modulo_de_produccion_usa_crear_o_finalizar():
    usos = []
    for archivo in (RAIZ / "src").rglob("*.py"):
        for n, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
            codigo = linea.split("#")[0]
            if (".crear(" in codigo or ".finalizar(" in codigo) and "def " not in codigo:
                usos.append(f"{archivo.relative_to(RAIZ)}:{n}")
    assert usos == []


def test_h8_resolver_rechaza_contencion_ajena(e):
    solicitada = OperacionAislamiento(MAC, TipoOperacion.AISLAR, ACTOR, T0).solicitar()
    e.repo.registrar_solicitud(solicitada)
    ajena = AccionAislamiento(mac_objetivo=MAC_2, fecha_inicio=T0, autorizado_por="u")
    with pytest.raises(ValueError):
        e.repo.resolver(solicitada.confirmar(T0, ajena.id_aislamiento), ajena)
    assert e.repo.activos() == []
