# CYBERA — Motor de aislamiento: viabilidad e implementación

Fase final del módulo de aislamiento. Este informe explica por qué el motor real
para Windows se entrega como un adaptador **honesto que se declara no disponible**,
y no como un mecanismo de interrupción de tráfico.

## 1. Conclusión

**Sin control del router o del conmutador/punto de acceso, no existe en Windows un
mecanismo para contener selectivamente a OTRO dispositivo que sea, a la vez,
fiable y con recuperación controlada.** No es una laguna del software: es una
limitación física de una red doméstica conmutada. CYBERA integra el contrato del
motor de extremo a extremo, pero nunca afirma haber aislado nada que no pueda
verificar.

## 2. Mecanismos evaluados

| Mecanismo | ¿Contiene a otro dispositivo? | Recuperación controlada | Veredicto |
|---|---|---|---|
| Firewall de Windows (`netsh advfirewall` / WFP) | **No.** Solo filtra el tráfico que entra o sale de *este* PC. El tráfico entre el intruso y el router no pasa por aquí. | — | Inútil para el objetivo |
| Regla en el router (p. ej. OpenWrt por SSH) | Sí | Sí | Fuera de alcance: «no depender del router» |
| Control del conmutador/AP (802.1X, *port security*) | Sí | Sí | No disponible en una red doméstica típica |
| Envenenamiento de caché ARP (Scapy está instalado) | Parcial y **no fiable** | **No garantizable** | **Descartado por contrato** (ver §3) |

Comprobado en el entorno: `scapy` y `psutil` están instalados; `pydivert`/Npcap no.
Es decir, el ARP spoofing sería *técnicamente* posible, pero se descarta por los
motivos de §3.

## 3. Por qué no se implementa ARP spoofing

El único mecanismo que operaría sin router ni conmutador es envenenar la caché ARP
del intruso (y/o del router). Se descarta porque incumple los propios requisitos de
la fase:

1. **Es una técnica de ataque, no de contención.** Mecánicamente es una denegación
   de servicio dirigida / *man-in-the-middle* contra el equipo de otro.
2. **No garantiza recuperación controlada.** La caché del objetivo se re-envenena
   con cada ARP legítimo del router, obligando a reinyectar sin pausa; al soltar, la
   restauración depende de que el objetivo reciba a tiempo el ARP correcto. El
   requisito «si no puede garantizar una recuperación controlada, detén la
   implementación» se cumple: **condición de parada alcanzada.**
3. **Afecta a terceros.** El tráfico ARP masivo degrada las tablas de otros equipos;
   incumple «no afectar dispositivos ajenos al objetivo».
4. **Produciría estados falsos.** `status()` no tendría evidencia real de contención
   (el objetivo puede ignorar el ARP, usar entradas estáticas o reconectar), así que
   honestamente devolvería `DESCONOCIDO` casi siempre → todo quedaría `UNCERTAIN`. Un
   motor que nunca confirma no es un motor funcional.

## 4. Lo implementado

- **`src/infrastructure/network/windows_isolation.py` — `WindowsIsolationEngine`.**
  Cumple `INetworkIsolation`:
  - `disponible()` → `False`, sin tocar la red y sin excepciones. El motivo técnico
    queda en `motivo_no_disponible` y se registra una vez (sin datos personales).
  - `isolate`/`release` → lanzan `OperacionNoEjecutadaError`. Por contrato, eso
    significa «no se tocó la red», así que `IsolationService` lo trata como fallo
    **conocido** (FAILED), nunca como resultado incierto.
  - `status()` → `DESCONOCIDO` (sin evidencia de contención).
  - Sin estado: las MAC distintas son independientes; `status`/`disponible` no
    tienen efectos secundarios.
- **`src/infrastructure/network/motor_aislamiento.py` — `crear_motor()`.** Inyecta el
  motor real por defecto. `CYBERA_MOTOR=ninguno` lo desactiva (comportamiento
  observable idéntico). No hay opción de motor ARP.
- **`src/app/main.py`.** Usa `crear_motor()` en lugar de `motor=None`. La aplicación
  se comporta igual que antes —el aislamiento informa «no disponible»— pero con el
  contrato integrado de verdad.
- **El motor simulado (`tests/dobles.py::MotorSimulado`) se mantiene** para las
  pruebas unitarias de la lógica. No se sustituye por el real en esas pruebas.

## 5. Cómo iniciar y probar

```powershell
# Desde la raíz del proyecto, en Windows 10/11 con Python 3.14 y PySide6.
python -m pip install -r requirements.txt
python iniciar.py            # Inicia CYBERA

# Pruebas (sin tráfico de red; usan motor simulado o el real honesto):
python -m pytest -q
python -m pytest -q tests/test_motor_windows.py    # Contrato del motor real
```

En la aplicación, «Aislar» (Dispositivos / Lista blanca) y «Desbloquear»
(Aislamiento) informan que la operación **no está disponible** y no marcan ni
persisten ningún aislamiento, que es el comportamiento correcto y honesto.

## 6. Resultados de las pruebas (reales, simuladas)

- Suite completa: **263 aprobadas, 1 omitida** (`test_red_real`, desactivada salvo
  que se defina `CYBERA_PRUEBA_RED=1`). Sin tráfico de red real.
- `tests/test_motor_windows.py`: **16 aprobadas** — contrato, disponibilidad,
  errores y la integración (la app inyecta un motor real no disponible y nunca
  persiste un aislamiento).

Estas pruebas son **simuladas**. No se realizaron, ni se declaran, pruebas de
aislamiento con dispositivos reales, porque el motor no interrumpe tráfico.

## 7. Evidencia de aislamiento y recuperación

No se puede aportar evidencia de aislamiento real: **no se implementó interrupción
de conectividad.** Lo verificable es el comportamiento del contrato y del flujo:
las operaciones terminan en FAILED/`NO_DISPONIBLE` o `ERROR_MOTOR` conocido, nunca
en un estado «aislado» o «desbloqueado» sin confirmación del motor.

## 8. Alternativa mínima para una demostración honesta

Si se necesita demostrar aislamiento y recuperación **reales** en un laboratorio
autorizado, la vía fiable y recuperable es aplicar la contención **en un router que
el estudiante controle** (p. ej. OpenWrt: añadir/quitar una regla de *firewall* por
MAC vía SSH). Eso es determinista y reversible, pero exige un router gestionado y
sus credenciales, por lo que queda fuera del alcance de esta fase («no depender del
router»). Las versiones históricas del proyecto (v5) exploraron esta ruta
(`OpenWrtFirewallIsolation`); podría reintroducirse como un `INetworkIsolation`
adicional si se autoriza ese entorno. No se implementa aquí para no introducir una
dependencia prohibida por el enunciado.

## 9. Limitaciones pendientes

- **No hay aislamiento de red real.** Es la limitación física descrita; requeriría
  control de la infraestructura (router o conmutador).
- **`disponible()` depende de la topología, no solo de privilegios.** Ejecutar como
  administrador no habilita el aislamiento; el mecanismo seguiría sin existir.
- **El motor ARP no se entrega** por ser una técnica de ataque sin recuperación
  garantizable (§3).
