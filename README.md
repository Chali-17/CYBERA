# CYBERA — Módulos Dispositivos y Configuración (red y monitoreo)

Control y aislamiento de dispositivos intrusos en redes inalámbricas con acceso
restringido al router del ISP. Aplicación de escritorio en Python + PySide6 para
Windows 10/11 con arquitectura MVC híbrida (Arquitectura de Software v2).

Implementado en esta entrega:

- **Dispositivos** (Mockup 03): inventario temporal de los dispositivos detectados
  realmente en la red, clasificados contra la lista blanca, con la acción
  «Revisar» → «Autorizar».
- **Configuración** (Mockup 09 + sección «Red y monitoreo»): selección de la
  interfaz de red real y activación/desactivación del monitoreo. La sección
  «Notificaciones externas» se conserva solo visualmente (controles deshabilitados).

Las demás opciones de navegación (Resumen, Lista blanca, Alertas, Aislamiento,
Bitácora, Reportes) se muestran de forma estática.

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
| `aislamientos.json` | Acciones de aislamiento: `idAislamiento`, `macObjetivo`, `fechaInicio`, `fechaFin`, `estado`, `autorizadoPor` (solo se escribe si el motor de red confirma un aislamiento real; ver §5 y §8) |

**El inventario de dispositivos detectados no se escribe en ningún archivo**:
existe solo en memoria y se descarta al desactivar el monitoreo, al cambiar de
interfaz o al cerrar la aplicación. El registro de errores va solo a la consola.

## 2. Pruebas

```powershell
python -m pytest -v                                        # 69 pruebas, sin tráfico de red
$env:CYBERA_PRUEBA_RED = "1"; python -m pytest tests\test_red_real.py -v -s   # red real
```

Las pruebas automáticas usan dobles de red (`tests/dobles.py`) y Qt en modo
`offscreen`. La prueba de red real es opcional porque envía solicitudes ARP a la subred.

Las pruebas del aislamiento (`tests/test_aislamiento.py`) usan un **motor doble
(simulado)** para verificar la lógica de `IsolationService`; **no** demuestran
que el aislamiento real de la red funcione, porque el motor de Capa 2 no existe
(ver §8). No hay ninguna prueba de integración con un mecanismo de aislamiento real.

## 3. Estructura

```
iniciar.py                      Lanzador
recursos/oui/manuf              Registro OUI (IEEE, vía Wireshark)
src/app/models/                 Modelo: PerfilDispositivo, DispositivoConfiable,
                                AccionAislamiento, ConfiguracionSistema, InterfazRed,
                                InventarioTemporal, MAC
src/app/services/               DeviceDiscoveryService, MonitoringService, WhitelistService,
                                IsolationService, SettingsService, NetworkInterfaceService
src/app/controllers/            MonitoringController, DeviceController, SettingsController,
                                TareaFondo (QThreadPool)
src/app/main.py                 Composición de dependencias
src/infrastructure/interfaces.py  Contratos (INetworkInterface, IArpProbe, IOuiResolver,
                                IHostnameResolver, IWhitelistRepository, ISettingsRepository,
                                IIsolationRepository, INetworkIsolation)
src/infrastructure/network/     Adaptadores Windows: interfaces, ARP, OUI, hostname
src/infrastructure/persistence/ Repositorios JSON con escritura atómica (incl. aislamientos)
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
  `aislamientos.json` y el dispositivo se retira de la tabla. Como el motor de
  red de Capa 2 todavía no existe (ver §8), hoy esta acción informa que el
  aislamiento no está disponible y **no** marca ni persiste nada.

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
| `SendARP` + `Get-NetNeighbor` en lugar de Scapy/Npcap | Sin dependencias ni controladores; funciona sin privilegios y detecta equipos que bloquean ping. |
| Cmdlets de PowerShell con salida JSON | No dependen del idioma del sistema (a diferencia de `arp -a` o `ipconfig`). |
| Archivo `manuf` de Wireshark como fuente OUI | El portal del IEEE rechaza las descargas automáticas. `manuf` se genera a partir de los registros MA-L, MA-M y MA-S del IEEE. Se incluye en el proyecto (3 MB) y funciona sin conexión. Actualizarlo: descargar `https://www.wireshark.org/download/automated/data/manuf` sobre `recursos/oui/manuf`. |
| Única dependencia: PySide6 (pytest solo para pruebas) | Requisito de no añadir dependencias innecesarias. |
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

## 8. Puntos pendientes de integración

- **Lista blanca (módulo propio):** ver, editar alias, retirar, alta manual e
  importación (CU-04). Este módulo solo agrega desde el escaneo (`origenRegistro = ESCANEO`).
- **Bitácora:** RI-09 exige registrar `AUTORIZACION_DISPOSITIVO`, `CONEXION` y
  `DESCONEXION`. Requiere `LogService`/`bitacora.jsonl`, que corresponden al módulo
  Bitácora. Puntos de enganche: `DeviceController._revisar` (autorización) e
  `InventarioTemporal.actualizar` (altas y bajas).
- **Alertas (CU-05):** generar `AlertaIntrusion` para cada MAC desconocida. Debe
  hacerlo `MonitoringService` tras clasificar. También debería enlazarse con el
  aislamiento: `AccionAislamiento.id_alerta_origen` queda hoy en `None` (RI-07).
- **Motor de red de aislamiento (lo que falta para aislar de verdad):** la
  cadena de aislamiento está preparada —`IsolationService` (validación, RI-05,
  verificación por `status`, persistencia), el repositorio `aislamientos.json` y
  el contrato `INetworkIsolation`—, pero **no existe un adaptador concreto** que
  implemente `isolate`/`release`/`status` sobre la Capa 2 (p. ej. manipulación
  ARP). Ese motor requiere privilegios de administrador y captura de paquetes
  (Npcap/Scapy) y pertenece al módulo de defensa activa. Mientras no se inyecte
  (`IsolationService(motor=...)` en `app/main.py`, hoy `motor=None`), el botón
  «Aislar» informa que la operación no está disponible y no simula nada. El
  estado `AISLADO` del modelo de dominio tampoco lo asigna este módulo.
- **Intervalo de escaneo:** fijo en 30 s (`INTERVALO_ESCANEO_S`). La documentación no
  define un campo configurable para el intervalo.
- **Privilegios (RNF03 / CU-01):** no se solicitan, porque este módulo no los
  necesita. Serán necesarios para la captura pasiva y el aislamiento (PrivilegeManager).
- **Notificaciones externas (CU-02):** la sección se ve igual que en el Mockup 09,
  pero sin acciones. Se omitió el texto «✓ Canal verificado», porque afirmaría una
  verificación que no ocurrió.
- **Asistente de configuración inicial (Mockup 01 / RF11)** y **bandeja del sistema (RF07)**: no implementados.
