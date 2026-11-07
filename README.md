# CYBERA — Módulos Dispositivos, Lista blanca y Configuración

Control y aislamiento de dispositivos intrusos en redes inalámbricas con acceso
restringido al router del ISP. Aplicación de escritorio en Python + PySide6 para
Windows 10/11 con arquitectura MVC híbrida (Arquitectura de Software v2).

Implementado en esta entrega:

- **Dispositivos** (Mockup 03): inventario temporal de los dispositivos detectados
  realmente en la red, clasificados contra la lista blanca, con la acción
  «Revisar» → «Autorizar» / «Aislar».
- **Lista blanca** (Mockup 04): directorio persistente de dispositivos autorizados,
  con alta (navega a Dispositivos), edición de alias, eliminación y aislamiento
  desde el diálogo «Editar».
- **Aislamiento** (Mockup 06): dispositivos bajo contención registrada, con una
  operación en curso o pendientes de recuperación, con la acción «Desbloquear».
  El motor de red real aplica contención por envenenamiento ARP cuando el equipo
  cumple los requisitos (ver §8); si no, informa «no disponible».
- **Configuración** (Mockup 09 + sección «Red y monitoreo»): selección de la
  interfaz de red real y activación/desactivación del monitoreo. La sección
  «Notificaciones por correo electrónico» es funcional: pide solo el correo
  remitente y la contraseña de aplicación de Gmail, permite guardar y enviar un
  correo de prueba, y envía una alerta cuando se detectan dispositivos nuevos.
  La contraseña se guarda en el Administrador de credenciales de Windows (nunca
  en archivos del proyecto). Ver §9.
- **Bitácora** (módulo de eventos): registro automático de `CONEXION`, `DESCONEXION`,
  `BLOQUEO`, `DESBLOQUEO` (y `AUTORIZACION_DISPOSITIVO`) en `bitacora.json`, con
  pantalla de historial: tabla con fecha/hora, tipo, dispositivo, MAC, descripción y
  resultado; filtros por tipo y rango de fechas (combinables); recarga y depuración con
  confirmación (CU-10).
- **Reportes** (módulo de exportación): genera reportes en **CSV** y **PDF** a partir del
  historial registrado en la bitácora, con los mismos filtros por tipo y rango de fechas
  y con la opción de exportar todo el historial.

Las demás opciones de navegación (Resumen) se
muestran de forma estática. El módulo **Alertas** (Mockup 05) fue retirado del
alcance funcional: sus funciones se consideran redundantes con Dispositivos, por
lo que ya no aparece en la barra de navegación.

## 1. Instalación y ejecución (Windows 10/11)

Requisitos: Python 3.11 o superior (probado con Python 3.14.3) y PowerShell 5.1
(incluido en Windows).

```powershell
cd C:\Users\angel\OneDrive\Documentos\DESARROLLO_PG_2
python -m pip install -r requirements.txt
python iniciar.py
```

Primer uso:

1. Abra **Configuración** y elija la interfaz en «Interfaz de red» (Wi-Fi o Ethernet).
   La elección se guarda al seleccionarla.
2. Pulse **Activar monitoreo**.
3. Abra **Dispositivos**. El primer barrido de una red /24 tarda unos 15–30 segundos.

No se necesitan privilegios de administrador ni controladores adicionales (Npcap)
para este módulo.

### Archivos locales

En `%APPDATA%\CYBERA\` (se puede cambiar con la variable de entorno `CYBERA_DATOS`):

| Archivo | Contenido |
|---|---|
| `configuracion.json` | `interfazId`, `nombreInterfaz`, `tipoInterfaz`, `estadoMonitoreo`, `fechaConfiguracion` |
| `lista_blanca.json` | Dispositivos autorizados: `mac`, `alias`, `fechaAutorizacion`, `origenRegistro`, `activo` |
| `aislamientos.json` | Formato 2. `aislamientos`: contenciones registradas al confirmarlas el motor (`idAislamiento`, `macObjetivo`, `fechaInicio`, `fechaFin`, `estado` ACTIVO/INACTIVO, `autorizadoPor`). `operaciones`: solicitudes de aislamiento/desbloqueo y su resultado (`idOperacion`, `macObjetivo`, `tipo`, `estado` REQUESTED/CONFIRMED/FAILED/UNCERTAIN, `motivoFallo`, `detalle`, `fechaSolicitud`, `fechaResolucion`, `idAislamiento`, `solicitadoPor`, `idRecuperacion`). Se sigue leyendo el formato 1. Ver «Máquina de estados del aislamiento». |
| `reportes/reporte_bitacora_YYYY-MM-DD.csv` | Reporte CSV generado por el módulo **Reportes** a partir del historial de `bitacora.json` (UTF-8 con BOM, separador CRLF). |
| `reportes/reporte_bitacora_YYYY-MM-DD.pdf` | Reporte PDF generado por el módulo **Reportes** a partir del historial de `bitacora.json`. |

**El inventario de dispositivos detectados no se escribe en ningún archivo**:
existe solo en memoria y se descarta al desactivar el monitoreo, al cambiar de
interfaz o al cerrar la aplicación. El registro de errores va solo a la consola.

## 2. Pruebas

```powershell
python -m pytest -v                                        # ~346 pruebas, sin tráfico de red
$env:CYBERA_PRUEBA_RED = "1"; python -m pytest tests\test_red_real.py -v -s   # red real
```

Las pruebas automáticas usan dobles de red (`tests/dobles.py`) y Qt en modo
`offscreen`. La prueba de red real es opcional porque envía solicitudes ARP a la subred.

Las pruebas del módulo **Bitácora** (`tests/test_bitacora.py`) cubren el registro
automático de los eventos y su persistencia. Las pruebas del módulo **Reportes**
(`tests/test_reportes.py`) cubren la generación de reportes CSV y PDF a partir del
historial, los filtros aplicados y la exportación con eventos vacíos.

Las pruebas del aislamiento (`tests/test_aislamiento.py` y
`tests/test_maquina_estados_aislamiento.py`, `tests/test_correcciones_auditoria.py`,
`tests/test_limitaciones_previas_motor.py`)
usan un **motor doble
(simulado)** para verificar la lógica de `IsolationService`. Las pruebas del motor
real de envenenamiento ARP (`tests/test_motor_arp.py`) usan dobles de
emisor/resolutor y **no** envían tráfico: verifican el contrato, la construcción
de las tramas y la restauración, no la eficacia real del envenenamiento en una red
concreta. Solo la prueba opcional (`test_envenenamiento_real_y_restauracion`, con
`CYBERA_PRUEBA_RED=1`) envenena de verdad un dispositivo de laboratorio.

## 3. Estructura

```
iniciar.py                      Lanzador
recursos/oui/manuf              Registro OUI (IEEE, vía Wireshark)
src/app/models/                 Modelo: PerfilDispositivo, DispositivoConfiable,
                                AccionAislamiento, ConfiguracionSistema, InterfazRed,
                                InventarioTemporal, MAC, EventoBitacora
src/app/services/               DeviceDiscoveryService, MonitoringService, WhitelistService,
                                IsolationService, SettingsService, NetworkInterfaceService,
                                BitacoraService, ReporteService
src/app/controllers/            MonitoringController, DeviceController, SettingsController,
                                WhitelistController, TareaFondo (QThreadPool), BitacoraController,
                                ReporteController
src/app/main.py                 Composición de dependencias
src/infrastructure/interfaces.py  Contratos (INetworkInterface, IArpProbe, IOuiResolver,
                                IHostnameResolver, IWhitelistRepository, ISettingsRepository,
                                IIsolationRepository, INetworkIsolation, IBitacoraRepository)
src/infrastructure/network/     Adaptadores Windows: interfaces, ARP, OUI, hostname,
                                motor de envenenamiento ARP (arp_spoofing)
src/infrastructure/persistence/ Repositorios JSON con escritura atómica (incl. aislamientos,
                                bitácora, reportes)
src/presentation/               Estilos, componentes y vistas PySide6
tests/                          Pruebas automatizadas
```

Dirección de dependencias: vista → controlador → servicio → contratos; los
adaptadores de `infrastructure` implementan los contratos. La vista no accede a
repositorios ni a la red.

## 4. Cómo se detectan los dispositivos

En cada ciclo, y **solo en la interfaz configurada**:

1. Se consulta la interfaz por su identificador (`InterfaceGuid`). Si no existe,
   está desconectada o solo tiene una dirección 169.254.x.x, se informa el
   problema, se vacía la tabla y **no se cambia a otra interfaz**.
2. **Barrido ARP activo** con `SendARP` (iphlpapi.dll) a cada IP de la subred,
   usando como origen la IP de la interfaz (64 consultas en paralelo).
3. Entradas `Reachable` de la **tabla de vecinos** de esa interfaz (`Get-NetNeighbor`).
4. Unión por MAC; se descartan difusión, multicast, MAC nula y direcciones fuera de la subred.
5. **Fabricante** por OUI con el archivo `manuf` incluido (bloques de 24, 28 y 36 bits).
   No se consulta Internet.
6. **Hostname** por resolución inversa (`gethostbyaddr`: DNS, LLMNR/NetBIOS), en
   paralelo y con un límite de 6 s. El resultado se guarda en una caché en memoria durante 10 minutos.
7. **Filtrado** (regla de consistencia): la pantalla Dispositivos muestra
   exclusivamente **lo detectado − lo autorizado − lo aislado**. Una MAC activa
   en `lista_blanca.json` o con un aislamiento activo en `aislamientos.json` se
   excluye de la tabla; el resto se muestra como «Desconocido» para su revisión.
   El filtro se aplica en `MonitoringService` (capa de servicio), tomando los
   repositorios como fuente de verdad; la vista no oculta filas por su cuenta.

El ciclo corre en un hilo de `QThreadPool`. El siguiente ciclo empieza 30 s
después de que termina el anterior. Los resultados de un ciclo que termina
después de desactivar el monitoreo o de cambiar de interfaz se descartan.

### Revisar, autorizar y aislar

En la tabla, cada fila tiene la acción **Revisar**, que abre un diálogo con los
datos reales del dispositivo y ofrece **Autorizar** o **Aislar** (no se añadieron
botones a la tabla):

- **Autorizar** registra la MAC en `lista_blanca.json` y el dispositivo
  desaparece de la tabla al actualizar el inventario, sin cerrar la aplicación.
  Si la autorización falla, el dispositivo permanece visible.
- **Aislar** pide una confirmación que identifica el dispositivo por IP y MAC y
  advierte de la pérdida de conectividad, e invoca el **IsolationService** real.
  Solo si el motor de red confirma el aislamiento se registra en
  `aislamientos.json` y el dispositivo se retira de la tabla. El motor por
  defecto aplica contención por envenenamiento ARP cuando el equipo cumple los
  requisitos (Windows + administrador + Npcap + interfaz conectada, ver §8); si
  no, esta acción informa que el aislamiento no está disponible y **no** marca ni
  persiste nada.

### Módulo Lista blanca (Mockup 04)

La pantalla **Lista blanca** es el directorio persistente de dispositivos
autorizados. Lee sus registros de `lista_blanca.json` (fuente de verdad única;
no mantiene copias propias) y los muestra en una tabla de cinco columnas —
**Alias, MAC, Fecha, Estado, Acción**— con un único botón **Agregar**. No hay
importación ni exportación (fuera de alcance).

- **Agregar** navega a Dispositivos; desde allí se autoriza un equipo detectado
  con «Revisar» → «Autorizar». Al volver a Lista blanca, el registro aparece
  (la tabla se recarga al mostrarse la pantalla).
- **Editar** (por fila) abre un diálogo que muestra MAC, IP, fabricante, nombre
  de host (estos tres solo si el equipo está detectado en la red ahora; si no,
  «No disponible», sin inventarlos), fecha de autorización, estado de
  autorización y estado de aislamiento. Desde el diálogo:
  - **Guardar**: edita solo el alias del registro existente (la MAC es el
    identificador y no se modifica); persiste y se refleja de inmediato.
  - **Eliminar de lista blanca**: pide confirmación (alias + MAC) y retira la
    autorización. No aísla, no bloquea conectividad y **no** elimina un
    aislamiento existente. Si falla, el registro permanece visible.
  - **Aislar**: invoca el `IsolationService` real. Como todo registro de esta
    pantalla está autorizado, la regla **RI-05** lo protege (no se aísla un
    dispositivo de confianza) y, además, falta el motor de red (§8); por eso la
    acción informa la limitación y nunca marca el dispositivo como aislado.

Autorización y aislamiento son estados independientes y así se mantienen.

### Máquina de estados del aislamiento

Se separan tres conceptos, cada uno con una sola fuente de verdad:

| Concepto | Dónde vive | Quién lo cambia |
|---|---|---|
| Autorización | `lista_blanca.json` | WhitelistService |
| Operación solicitada (AISLAR / DESBLOQUEAR) | `aislamientos.json` → `operaciones` | IsolationService |
| Contención confirmada (ACTIVO / INACTIVO) | `aislamientos.json` → `aislamientos` | IsolationService, solo al confirmar |

Estados de una operación (`app/models/operacion_aislamiento.py`):

```
PENDING ──► REQUESTED ──► CONFIRMED
   │            ├───────► UNCERTAIN   (efecto de red desconocido: requiere recuperación)
   └──► FAILED ◄┘                     (CONFIRMED, FAILED y UNCERTAIN son terminales)
```

- **FAILED**: el efecto de red es CONOCIDO (no se envió nada, el motor garantizó
  no tocar la red, o `status()` devolvió el valor contrario del contrato).
- **UNCERTAIN**: la orden pudo llegar al motor pero no se sabe qué dejó aplicado.
  La MAC queda **pendiente de recuperación** hasta que una operación posterior
  sobre ella llegue a CONFIRMED; esa operación queda enlazada en
  `idRecuperacion` y la evidencia original se conserva. **Nunca se reintenta nada
  automáticamente.** La recuperación es explícita: «Desbloquear» en la pantalla
  Aislamiento (release + verificación SIN_CONTENCION), que se permite aunque no
  haya contención registrada («desbloqueo de recuperación»).

| Transición | Cuándo | Persistencia |
|---|---|---|
| — → PENDING | Acción explícita del usuario, tras validar MAC, actor, lista blanca y estado actual | Solo memoria |
| PENDING → FAILED (`NO_DISPONIBLE`) | No hay motor o `disponible()` es False | No se escribe: no se envió nada |
| PENDING → FAILED (`ERROR_REGISTRO`) | No se pudo escribir la solicitud | No se escribe; el motor no se invoca |
| PENDING → REQUESTED | Solicitud escrita en disco **antes** de invocar al motor | Se escribe |
| REQUESTED → CONFIRMED | `status()` devuelve `CONTENCION_APLICADA` (aislar) o `SIN_CONTENCION` (desbloquear), y la MAC sigue sin autorizar | Una sola escritura: operación + contención creada/finalizada |
| REQUESTED → FAILED (`ERROR_MOTOR`) | El motor lanza `OperacionNoEjecutadaError` (garantiza que no tocó la red) | Se escribe; la contención no cambia |
| REQUESTED → UNCERTAIN (`ERROR_MOTOR`) | El motor lanza cualquier otra excepción | Se escribe; la contención no cambia; requiere recuperación |
| REQUESTED → FAILED (`SIN_CONFIRMACION`) | `status()` devuelve el valor contrario (`SIN_CONTENCION` al aislar, `CONTENCION_APLICADA` al desbloquear) | Se escribe; la contención no cambia |
| REQUESTED → UNCERTAIN (`SIN_CONFIRMACION`) | `status()` devuelve `DESCONOCIDO` o un valor ajeno al contrato | Se escribe; requiere recuperación |
| REQUESTED → FAILED (`AUTORIZADA`) | La MAC apareció en la lista blanca: antes del motor (no se envía nada) o tras `CONTENCION_APLICADA` con reversión **verificada** | Se escribe; no se crea contención |
| REQUESTED → UNCERTAIN (`REVERSION_FALLIDA`) | Tras `CONTENCION_APLICADA` la MAC apareció en la lista blanca y la reversión no se pudo verificar | Se escribe (con la causa en `detalle`); requiere recuperación |
| REQUESTED → FAILED (`AUTORIZACION_NO_VERIFICABLE`) | No se pudo leer la lista blanca al revalidar | Igual que `AUTORIZADA` |
| REQUESTED → UNCERTAIN (`INTERRUMPIDA`) | Al iniciar la aplicación o antes de una nueva solicitud sobre la misma MAC | Se escribe; nunca se da por confirmada; requiere recuperación |

**Contrato `INetworkIsolation.status()` → `EstadoContencion`** (sustituye a
`EstadoRed`, cuyo valor `ACTIVO` era ambiguo):

| Valor | Significado |
|---|---|
| `CONTENCION_APLICADA` | El motor confirma que aplica contención al objetivo |
| `SIN_CONTENCION` | El motor confirma que NO aplica contención (no prueba que haya conectividad) |
| `DESCONOCIDO` | No puede determinarlo. Obligatorio para una MAC que el motor no conoce |

Ningún valor describe la conectividad del dispositivo. Una excepción o cualquier
valor que no sea un `EstadoContencion` no confirma nada.

Solicitudes rechazadas (error inmediato, sin operación, sin escritura y sin
llamar al motor): MAC inválida o de difusión, usuario no identificado, MAC en la
lista blanca (RI-05, solo para aislar), aislar una MAC ya aislada, desbloquear
una MAC sin contención activa ni recuperación pendiente, y cualquier solicitud sobre una MAC que ya tiene
una operación en curso. Las transiciones fuera de la tabla lanzan
`TransicionInvalidaError`.

Reglas: la detección nunca aísla (solo `IsolationService.aislar`, invocado tras
la confirmación del usuario); una solicitud no equivale a éxito; el desbloqueo
no depende de la lista blanca; un fallo nunca borra la contención ni el historial.

**Concurrencia (dentro del proceso).** `ReservasPorMac`
(`app/services/reservas_mac.py`) es una reserva por MAC no bloqueante. Hay **un
único coordinador por carpeta de datos en todo el proceso**
(`coordinador_para`): todo `IsolationService` (aislar, desbloquear, verificar) y
todo `WhitelistService.autorizar` construidos sobre esos archivos lo comparten por
defecto, aunque se creen por separado. Del mismo modo, `JsonFile` usa un único
candado por archivo, así que dos repositorios sobre el mismo JSON no pierden
escrituras. Una segunda solicitud sobre una MAC ocupada se
rechaza al instante (`OperacionEnCursoError` o `AutorizacionBloqueadaError`); no
se encola. Así no puede autorizarse una MAC mientras se aísla, ni aislarse
mientras se autoriza. MAC distintas no comparten reserva, el motor trabaja fuera
de cualquier candado global y la reserva se libera en un `finally`. Además, el
servicio **revalida la lista blanca** justo antes de invocar al motor y antes de
confirmar, para cubrir cambios que no pasen por `WhitelistService`.

**Entre procesos.** La única protección es la **instancia única**
(`infrastructure/instancia_unica.py`): un `QLockFile` en
`%APPDATA%\CYBERA\cybera.lock` (o en `CYBERA_DATOS`). Se toma antes de abrir ningún
archivo de datos. Si otra instancia viva lo tiene, CYBERA avisa y se cierra sin
tocar nada. El bloqueo se libera al salir, también si el arranque falla. Si el
proceso que lo tenía murió, Qt lo detecta por su PID y lo recupera. Los candados de
`JsonFile` y las reservas por MAC solo coordinan hilos de un mismo proceso.

**Persistencia.** Las escrituras son atómicas (temporal + `os.replace`). Un archivo
dañado, con versión no entera o desconocida (`true` no vale como 1) o con
registros contradictorios no se usa ni se sobrescribe. Antes de migrar un archivo
de formato 1 se guarda una copia exacta `aislamientos.json.v1.bak` (o
`.v1.N.bak`; nunca se sobrescribe una copia previa); si la copia falla, no se
migra. `crear()`/`finalizar()` del repositorio no forman parte de la interfaz:
son solo para pruebas y una prueba verifica que ningún módulo de `src` los usa.

**Registro frente a verificación.** Una contención ACTIVA en el JSON es un dato
administrativo. Lo que el motor responde con `status()` se guarda solo en
memoria. Tras reiniciar, toda contención registrada se muestra como
**«Registrado, estado sin verificar»** hasta que el motor la compruebe
(`IsolationService.verificar_registrados`, invocado al iniciar; sin motor no
consulta nada).

**Interfaz.** Los avisos distinguen «… no disponible», «… fallido», «Operación en
curso», «Resultado incierto: requiere recuperación», «… sin verificar» (el motor
actuó pero no se pudo registrar) y «No se pudo …» (rechazo). Los éxitos se
informan como «Contención confirmada» y «Contención retirada», sin afirmar
conectividad. En el diálogo de Lista blanca, «Estado de aislamiento» nunca dice
«Aislado» ni «No aislado» como hecho comprobado. Usa: «Sin aislamiento
registrado», «Aislamiento/Desbloqueo solicitado, sin confirmar», «Requiere
recuperación: resultado incierto del último …», «Registrado, estado sin
verificar», «Contención aplicada según el motor (verificado a las HH:MM:SS)»,
«Sin contención según el motor (…)», «Registrado como aislado, pero el motor no
aplica contención (…)» o «Estado sin verificar: …».

### Pantalla Aislamiento (Mockup 06)

Reproduce el Mockup 06 sin controles adicionales: título «Aislamiento»,
subtítulo «Gestión de dispositivos bajo contención», indicador de monitoreo y el
panel «Dispositivos aislados» con una tarjeta por dispositivo (nombre, IP, MAC,
fecha, insignia de estado y botón **Desbloquear**). Lista las MAC con contención
registrada, con una operación en curso o pendientes de recuperación.

| Insignia | Cuándo |
|---|---|
| **Aislado** (rojo, como el mockup) | Solo si el motor **verificó en esta ejecución** `CONTENCION_APLICADA` |
| **Sin verificar** (ámbar) | Registrado, pero sin verificación del motor en esta ejecución (p. ej. tras reiniciar o sin motor) |
| **Requiere recuperación** (ámbar) | Hay una operación UNCERTAIN sin resolver |
| **No coincide** (ámbar) | Registrado como aislado, pero el motor informa `SIN_CONTENCION` |
| **Aislando… / Desbloqueando…** (gris, botón desactivado) | Operación en curso |

La ayuda emergente de la insignia y del botón muestra el texto completo de la
situación. «Desbloquear» pide confirmación (identifica nombre, MAC e IP y avisa si
el resultado previo es incierto) y se ejecuta en segundo plano.

### Trabajo en segundo plano

`EjecutorAislamiento` (`app/controllers/ejecutor_aislamiento.py`) ejecuta
`aislar`/`desbloquear` en un `QThreadPool` mediante `TareaFondo` y devuelve el
resultado al hilo de la interfaz con señales Qt (conexión en cola). Las pantallas
Dispositivos, Lista blanca y Aislamiento comparten la misma instancia, creada en
`app/main.py`.

- Duplicados: una MAC con una petición pendiente o en ejecución no admite otra.
  La reserva por MAC del servicio la respalda.
- Errores: llegan como la excepción original, para elegir el aviso correcto.
- Cancelación solo si es segura: una petición aún en cola se puede retirar; una
  en ejecución, no (el motor pudo actuar en la red).
- Al cerrar, se retiran las peticiones en cola y se espera a las que están en
  ejecución.
- Los controladores construidos sin ejecutor (pruebas) usan uno síncrono con las
  mismas señales. Una prueba verifica que la aplicación real usa el asíncrono.

### Compatibilidad con versiones anteriores

Revisé sin modificarlas las versiones de `PG2_DESARROLLO` (ControlAislamiento, v3,
v4, v5, v6 y v7). Todas escriben en la carpeta fija `%APPDATA%\ControlAislamiento`,
sin forma de cambiarla, con un formato propio y sin conocer `cybera.lock`. CYBERA
usa `%APPDATA%\CYBERA`, así que por defecto nunca comparten archivos. Para que
tampoco ocurra por configuración, CYBERA **no arranca** (ni crea su bloqueo ni toca
nada) si la carpeta de datos se llama `ControlAislamiento` o contiene archivos que
solo escriben esas versiones (`dispositivos.json`, `alertas.json`,
`notificaciones.json`, `bitacora.jsonl`). Ver `infrastructure/compatibilidad_datos.py`.

### Contrato del motor de aislamiento

Contrato que cumplen los motores reales (`INetworkIsolation`,
`infrastructure/interfaces.py`): el de envenenamiento ARP
(`ArpSpoofingIsolationEngine`) y el honesto que se declara no disponible
(`WindowsIsolationEngine`).

| Método | Debe | No debe |
|---|---|---|
| `disponible() -> bool` | Ser rápido y sin efectos en la red. Devolver False si faltan privilegios de administrador, el adaptador configurado o el controlador de captura. | Lanzar excepciones (si lanza, se trata como no disponible). |
| `isolate(mac)` | Solicitar la contención, ser idempotente y terminar o lanzar en un tiempo acotado (≤ 30 s). Lanzar `OperacionNoEjecutadaError` si una comprobación previa falla **antes** de tocar la red. | Devolver éxito como prueba: su retorno no confirma nada. |
| `release(mac)` | Retirar **cualquier** contención propia sobre la MAC, incluso de una ejecución anterior (restaurar las tablas ARP afectadas). Ser idempotente y acotado. Mismo uso de `OperacionNoEjecutadaError`. | Afirmar después `SIN_CONTENCION` si no pudo garantizar la restauración. |
| `status(mac) -> EstadoContencion` | No tener efectos. Devolver `CONTENCION_APLICADA` solo si el motor aplica contención **ahora**, y `SIN_CONTENCION` solo si puede afirmar que no la aplica. En cualquier otro caso, `DESCONOCIDO`. | Devolver `SIN_CONTENCION` por defecto para una MAC que no conoce, ni afirmar conectividad. |

- **Operación verificada**: `IsolationService` llama a `status()` justo después de
  `isolate`/`release`, en el mismo proceso. Solo el miembro exacto
  `EstadoContencion.CONTENCION_APLICADA` (aislar) o `EstadoContencion.SIN_CONTENCION`
  (desbloquear) confirma. Cualquier otro valor, texto o excepción no confirma.
- **Errores**: `OperacionNoEjecutadaError` → FAILED (efecto conocido). Cualquier
  otra excepción → UNCERTAIN (requiere recuperación).
- **Valor contrario** de `status()` → FAILED. **`DESCONOCIDO` o un valor inválido**
  → UNCERTAIN.
- **Concurrencia**: nunca habrá dos llamadas simultáneas para la misma MAC; el
  motor debe tolerar llamadas paralelas para MAC distintas.
- **Reinicio**: al iniciar, `verificar_registrados()` consulta `status()` de cada
  contención registrada y solo anota la respuesta en memoria (no modifica el JSON).
- **Conectividad**: ningún valor del contrato describe la conectividad del
  dispositivo. Comprobarla sería una verificación independiente, fuera de este
  contrato.

### Motor real para Windows (envenenamiento ARP, disponible con requisitos)

El motor real por defecto (`infrastructure/network/arp_spoofing.py`,
`ArpSpoofingIsolationEngine`) implementa el contrato `INetworkIsolation` con un
mecanismo de contención de Capa 2: **envenenamiento de caché ARP dirigido a
«agujero negro»**. Para aislar una MAC se envían, de forma periódica, respuestas
ARP suplantadas con la MAC/IP propias del adaptador:

1. Al **objetivo**: «la IP del gateway está en mi MAC» → el objetivo envía su
   tráfico al gateway hacia este equipo, que no lo reenvía.
2. Al **gateway**: «la IP del objetivo está en mi MAC» → el gateway deja de
   entregar al objetivo el tráfico dirigido a él.

El objetivo pierde la conectividad con la red («agujero negro»). El aislamiento
solo se **confirma** si `status()` observa el bucle de envío activo y con al
menos una trama transmitida en esta ejecución; el registro en
`aislamientos.json` se hace, como siempre, solo tras esa confirmación.

**Requisitos (si faltan, el motor se declara no disponible y «Aislar» informa
«no disponible» sin tocar la red):** Windows, privilegios de administrador,
Npcap instalado y una interfaz conectada con IPv4. `crear_motor()` inyecta este
motor por defecto (`main.py`); la variable `CYBERA_MOTOR=windows` selecciona el
motor honesto que se declara no disponible y `CYBERA_MOTOR=ninguno` deja sin
motor.

**Limitaciones honestas de esta técnica (técnica de ataque, fiabilidad parcial):**

- Desde otro equipo del segmento se puede **restaurar** la caché ARP con un ARP
  legítimo; un punto de acceso con **DHCP snooping / Dynamic ARP Inspection**
  bloquea el envenenamiento.
- Un objetivo que obtenga conectividad por otra ruta (otra interfaz, otro
  segmento o IPv6) no queda contenido.
- La **restauración** al liberar (`release`) envía las entradas ARP **legítimas**
  (MAC real del objetivo y del gateway, obtenidas por resolución ARP) y se
  reenvía unas veces; es «en el mejor esfuerzo». Si no se pueden resolver los
  pares reales, no se puede garantizar la restauración y `status()` seguirá
  devolviendo `DESCONOCIDO` para esa MAC.
- No se envenena nunca una MAC autorizada en la lista blanca (RI-05 se mantiene):
  el envenenamiento solo se aplica a dispositivos no autorizados que pasan a
  aislamiento.
- **Uso exclusivo en un laboratorio autorizado.**

Análisis completo en
[`docs/INFORME_MOTOR_AISLAMIENTO.md`](docs/INFORME_MOTOR_AISLAMIENTO.md). El
motor simulado se mantiene solo para las pruebas unitarias; las pruebas del
motor ARP usan dobles de emisor/resolutor (no envían tráfico salvo
`CYBERA_PRUEBA_RED=1`).

## 5. Limitaciones conocidas del descubrimiento en Windows

- **La lista puede no ser completa.** Solo aparecen los equipos que respondieron
  a ARP o que Windows marcó como alcanzables. No responder **no significa estar
  desconectado**: un teléfono en reposo puede tardar en contestar. Por eso un
  equipo se mantiene durante 2 ciclos sin respuesta antes de retirarse de la lista.
- **Aislamiento de clientes del router/AP**: si el router impide que los clientes
  Wi-Fi se vean entre sí, esos equipos no son detectables desde este nodo.
- **Solo IPv4 y solo el segmento local.** Equipos detrás de otro router, en otra
  VLAN o solo con IPv6 no aparecen.
- **Subredes mayores que /22** (más de 1022 hosts) no se barren activamente; en
  ese caso solo se usa la tabla de vecinos, que es aún menos completa.
- **ICMP (ping) no se usa**: muchos equipos lo bloquean. ARP es obligatorio en
  IPv4 local y por eso es más fiable, pero tampoco garantiza una lista completa.
- **MAC aleatorias**: teléfonos y Windows usan MAC privadas por red. No tienen
  fabricante registrado (se muestra «No disponible (MAC aleatoria)») y un equipo
  autorizado puede volver a aparecer como desconocido si cambia su MAC.
- **Fabricante**: el OUI identifica al fabricante del adaptador de red, no
  necesariamente la marca del equipo. Ni la MAC ni el fabricante demuestran que un
  dispositivo sea seguro: una MAC puede falsificarse.
- **Hostname**: muchos teléfonos, televisores y equipos IoT no publican su nombre;
  entonces se muestra «Desconocido».
- **Rendimiento**: cada consulta a PowerShell tarda 0,5–1,5 s, y el barrido de una
  /24 unos 13 s, porque `SendARP` espera unos 3 s a cada IP que no responde. Un
  ciclo completo tarda unos 20–27 s en la red de prueba. Todo esto ocurre en segundo plano.
- El barrido deja entradas `Unreachable` en la tabla ARP de Windows. Es el
  comportamiento normal del sistema y no afecta a la red.

## 6. Decisiones técnicas

| Decisión | Motivo |
|---|---|
| `SendARP` + `Get-NetNeighbor` en lugar de Scapy/Npcap (descubrimiento) | Sin dependencias ni controladores; funciona sin privilegios y detecta equipos que bloquean ping. |
| Cmdlets de PowerShell con salida JSON | No dependen del idioma del sistema (a diferencia de `arp -a` o `ipconfig`). |
| Archivo `manuf` de Wireshark como fuente OUI | El portal del IEEE rechaza las descargas automáticas. `manuf` se genera a partir de los registros MA-L, MA-M y MA-S del IEEE. Se incluye en el proyecto (3 MB) y funciona sin conexión. Actualizarlo: descargar `https://www.wireshark.org/download/automated/data/manuf` sobre `recursos/oui/manuf`. |
| Dependencias: PySide6 (interfaz) y Scapy (motor ARP); pytest solo para pruebas | El descubrimiento no necesita controladores, pero el motor de envenenamiento ARP sí construye y transmite tramas, para lo que usa Scapy sobre Npcap. |
| Identificar la interfaz por `InterfaceGuid` | El nombre o el índice pueden cambiar; el GUID es estable. Nunca se sustituye por otra interfaz. |
| Escritura atómica (temporal + `os.replace`) y candado por archivo | Arquitectura 12.1. Un archivo dañado se informa y **nunca se sobrescribe**. |
| Lista blanca dañada ⇒ no se muestran dispositivos | Evita presentar como «Desconocido» a equipos que podrían estar autorizados. |
| Indicador con tres estados (ACTIVO / INACTIVO / CON INCIDENCIA) | Diseño de Interfaz §2: el usuario debe distinguir activo, detenido o con problema. Se usa el mismo elemento visual del mockup. |
| Mensajes de estado dentro del panel de la tabla | Informan el estado sin añadir controles nuevos. |

## 7. Contradicciones detectadas en la documentación y cómo se resolvieron

1. **Acción en filas confiables.** El Mockup 03 muestra «Autorizar» en filas ya
   «Confiable». Por decisión del responsable: Desconocido → **Revisar** (diálogo con
   los datos reales y alias opcional → «Autorizar»); Confiable → texto «Autorizado».
2. **Persistencia del inventario.** El Modelo de datos define `dispositivos.json`
   y la regla RI-12, que conserva el perfil de un dispositivo desconectado. El
   requerimiento de este módulo prohíbe persistir el inventario. Se siguió el
   requerimiento: `dispositivos.json` no existe.
3. **Nombres de archivos.** La Arquitectura usa `settings.json` y `whitelist.json`;
   el Modelo de datos usa `configuracion.json` y `lista_blanca.json`. Se usaron los
   del Modelo de datos, que es más detallado.
4. **Botón de escaneo/actualización.** El Diseño de Interfaz lo menciona para el
   Mockup 03, pero el mockup no lo muestra y el requerimiento prohíbe controles
   nuevos. No se añadió: el escaneo es automático mientras el monitoreo está activo.
5. **Técnica de captura.** CU-03 y la Arquitectura describen una «captura pasiva de
   tramas de Capa 2». Eso requiere Npcap y privilegios. Para este módulo se usó
   descubrimiento ARP activo. El contrato `IArpProbe` permite añadir más adelante
   un adaptador de captura pasiva sin cambiar los servicios ni las vistas.
6. **Tipo de interfaz.** El Modelo de datos solo admite ETHERNET y WIFI. Se añadió
   OTRO (Bluetooth, VPN, adaptadores virtuales) porque RF12 pide no restringir por hardware.
7. **Alias al autorizar.** RF02 pide autorizar «con un clic»; CU-04 incluye confirmar
   la MAC y asignar un alias. Se aplicó CU-04: confirmación con alias opcional.
8. **Insignia «Aislado» del Mockup 06.** El mockup muestra «Aislado» en todas las
   filas, pero los requisitos exigen no presentar como comprobado un estado sin
   verificar. Se conservó la insignia roja «Aislado» solo cuando el motor lo
   verificó en esta ejecución. Los demás casos usan el mismo elemento con otro texto
   y tono («Sin verificar», «Requiere recuperación», «No coincide», «Desbloqueando…»).
   No se añadieron controles: la única acción sigue siendo «Desbloquear».

## 8. Puntos pendientes de integración

- **Lista blanca — alta manual e importación/exportación (fuera de alcance):**
  el módulo Lista blanca ya permite ver, editar alias y retirar (CU-04). El alta
  se hace desde el escaneo (`origenRegistro = ESCANEO`, vía Dispositivos). El
  alta manual escribiendo una MAC (`origenRegistro = MANUAL`) y la importación/
  exportación (`IMPORTACION`) quedan explícitamente fuera del alcance de esta
  entrega.
- **Bitácora:** ✅ **Implementado** en esta entrega. RI-09 exige registrar `AUTORIZACION_DISPOSITIVO`, `CONEXION` y `DESCONEXION`;
  el alcance del usuario amplió el registro con `BLOQUEO` / `DESBLOQUEO` (resultado `EXITOSO` / `FALLO`).
  Se implementó el módulo completo: modelo `EventoBitacora`, repositorio `JsonBitacoraRepository`
  (`bitacora.json`), servicio `BitacoraService`, pantalla **Bitácora** (tabla, filtros por tipo y
  rango de fechas, recarga y depuración con confirmación) y pruebas (`tests/test_bitacora.py`).
  La persistencia reutiliza el mecanismo `JsonFile` existente; el módulo **Reportes** consume el
  historial a través del mismo `BitacoraService` sin duplicar la lógica de almacenamiento.
- **Reportes:** ✅ **Implementado** en esta entrega. El módulo **Reportes** consulta el historial de
  la bitácora (vía `BitacoraService`, sin acceso a persistencia directa) y exporta los eventos a
  **CSV** (`reporte_bitacora_YYYY-MM-DD.csv`, UTF-8 con BOM, CRLF y escapes RFC 4180, sin fórmulas
  de hoja de cálculo) e **PDF** (`reporte_bitacora_YYYY-MM-DD.pdf`, reportlab: título, fecha de
  generación, filtros aplicados, tabla con encabezados repetidos y numeración de páginas) en la
  carpeta `reportes/`. La pantalla **Reportes** ofrece filtros por tipo y rango de fechas, la opción
  de exportar todo el historial o solo los filtrados, y estados de carga/error sin registros. No
  modifica ni elimina registros de la bitácora. Pruebas: `tests/test_reportes.py`.
- **Alertas (CU-05): retirado del alcance funcional.** No se desarrolla la
  pantalla de Alertas (Mockup 05); sus funciones se consideran redundantes con
  Dispositivos. Discrepancia documentada a corregir después: el modelo de
  Aislamiento conserva el campo opcional `AccionAislamiento.id_alerta_origen`
  (RI-07), que queda siempre en `None` al no existir Alertas; se mantiene para no
  alterar el módulo de Aislamiento ni su formato de persistencia. Los mockups y
  diagramas que aún muestren «Alertas» son documentación histórica de referencia
  académica y no reflejan el alcance implementado.
- **Aislamiento de red real (envenenamiento ARP):** la cadena está completa
  —`IsolationService`, el repositorio `aislamientos.json`, el contrato
  `INetworkIsolation` y el motor real `ArpSpoofingIsolationEngine`— y el motor
  aplica contención por **envenenamiento de caché ARP dirigido a agujero negro**
  cuando el equipo cumple los requisitos (Windows, administrador, Npcap e
  interfaz conectada). Es una técnica de **ataque**, de fiabilidad parcial y sin
  recuperación garantizable al 100 % (ver «Motor real para Windows»); se
  recomienda un entorno de laboratorio autorizado. Si faltan los requisitos,
  «Aislar»/«Desbloquear» informan «no disponible» y no persisten nada. Para una
  contención fiable y recuperable de verdad sigue siendo necesaria la
  infraestructura gestionada (p. ej. una regla por MAC en un router propio). Ver
  [`docs/INFORME_MOTOR_AISLAMIENTO.md`](docs/INFORME_MOTOR_AISLAMIENTO.md).
- **Una sola instancia por carpeta de datos:** la exclusión entre procesos depende
  del `QLockFile`. Dos instancias con carpetas de datos distintas (por ejemplo,
  con `CYBERA_DATOS` diferente) no se coordinan, y tampoco lo hace un programa
  ajeno que edite los JSON a mano. Las versiones anteriores no pueden compartir
  carpeta con CYBERA (ver «Compatibilidad con versiones anteriores»).
- **Reservas explícitas:** el coordinador por MAC es único por carpeta salvo que
  se pase a mano otra `ReservasPorMac` al construir un servicio (solo lo hacen
  algunas pruebas). Producción no lo hace.
- **Sin cancelación de una operación en ejecución:** por seguridad, solo se puede
  retirar una petición que aún no empezó. Si el motor no respeta su tiempo
  acotado, el cierre de la aplicación espera hasta 30 s.
- **Verificación sin motor:** con `motor=None`, toda contención registrada se ve
  como «Registrado, estado sin verificar». La pantalla Dispositivos sigue
  excluyendo esas MAC porque se basa en el registro administrativo.
- **Historial sin retención:** `operaciones` crece sin límite; su depuración
  corresponde al módulo Bitácora.
- **Intervalo de escaneo:** fijo en 30 s (`INTERVALO_ESCANEO_S`). La documentación no
  define un campo configurable para el intervalo.
- **Privilegios (RNF03 / CU-01):** no se solicitan, porque este módulo no los
  necesita. Serán necesarios para la captura pasiva y el aislamiento (PrivilegeManager).
- **Notificaciones por correo (CU-02):** implementado para Gmail SMTP. Se envía un
  único correo por grupo de dispositivos nuevos de un mismo ciclo de detección (no uno
  por dispositivo), al propio correo remitente. Un fallo SMTP no detiene el monitoreo.
  El destinatario independiente y otros canales (Telegram/WhatsApp) quedan como
  ampliación futura. Ver §9.
- **Asistente de configuración inicial (Mockup 01 / RF11)** y **bandeja del sistema (RF07)**: no implementados.

## 9. Notificaciones por correo (Gmail SMTP)

Cuando el monitoreo detecta dispositivos **nuevos** (MAC que entra por primera vez
al inventario temporal, no una actualización de uno ya conocido), se envía **un solo
correo por grupo** con la lista de todos los dispositivos de ese ciclo. Si se
detectan 10 a la vez, es **un** correo con los 10; si luego aparece otro grupo, es
otro correo. Un dispositivo ya conocido no vuelve a generar alerta.

**Configuración (pantalla Configuración):** solo se piden dos datos:

- Correo electrónico remitente (una dirección de Gmail).
- Contraseña de aplicación de Gmail (campo oculto, con botón «Mostrar»).

Los valores técnicos son internos y fijos: `smtp.gmail.com`, puerto **465** con TLS
implícito (`SMTP_SSL`); el usuario y el remitente son el correo ingresado. El
destinatario actual es el propio remitente.

**Seguridad de las credenciales:**

- La contraseña de aplicación se guarda en el **Administrador de credenciales de
  Windows** (biblioteca `keyring`, backend WinVault), nunca en archivos del proyecto.
- `notificaciones.json` (en `%APPDATA%\CYBERA`) guarda **solo** el correo remitente.
- La contraseña no se devuelve a la interfaz, no se escribe en logs ni en mensajes de
  error, y un campo de contraseña vacío al editar **no** sobrescribe la ya guardada.

**Cómo crear una contraseña de aplicación de Gmail:** Cuenta de Google → Seguridad →
activar **Verificación en dos pasos** → **Contraseñas de aplicaciones** → generar una
para «Correo»; se usa esa contraseña de 16 caracteres (no la contraseña habitual).

**Robustez:** el envío ocurre en un hilo aparte (no bloquea el monitoreo). Un fallo
SMTP no detiene el monitoreo; los fallos reintentables se reintentan con una política
prudente, sin duplicar un correo ya aceptado por Gmail. Si no hay configuración, el
monitoreo funciona con normalidad y no se envía nada.
