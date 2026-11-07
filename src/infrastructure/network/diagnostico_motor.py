"""Diagnóstico de capacidades de red para el motor de aislamiento (SOLO LECTURA).

Comprueba, sin modificar ni interrumpir el tráfico y sin suplantar direcciones,
qué capacidades reales ofrece el equipo para un eventual motor de contención:

- Privilegios del proceso (administrador o no).
- Presencia y estado de Npcap (captura de paquetes).
- Adaptador de red en uso.
- Observación PASIVA del tráfico: cuánto y de qué tipo se ve en la interfaz
  (difusión, multidifusión, unicast propio y —lo decisivo— unicast de OTROS
  equipos), para saber si el PC siquiera puede observar el tráfico del objetivo.

NADA de esto habilita el aislamiento: ``WindowsIsolationEngine`` sigue declarándose
no disponible. Este módulo solo informa; no envía ni descarta paquetes. La captura
pasiva es opcional (requiere Npcap y, normalmente, privilegios) y nunca se ejecuta
en las pruebas unitarias salvo que se pida explícitamente.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger(__name__)

# MAC de difusión y prefijos de multidifusión (IPv4, IPv6, STP) para clasificar.
_BROADCAST = "ff:ff:ff:ff:ff:ff"
_MCAST_PREFIJOS = ("01:00:5e", "33:33", "01:80:c2")


def tiene_privilegios_admin() -> bool:
    """True si el proceso tiene privilegios de administrador. Solo diagnóstico."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - fuera de Windows o API no disponible
        return False


@dataclass(frozen=True)
class EstadoNpcap:
    instalado: bool
    operativo: bool          # Driver presente y DLLs accesibles.
    detalle: str


def estado_npcap() -> EstadoNpcap:
    """Comprueba Npcap sin usarlo: presencia de sus DLLs y del controlador.

    No abre ninguna captura ni toca la red.
    """
    system32 = Path(r"C:\Windows\System32")
    wpcap = system32 / "wpcap.dll"
    packet = system32 / "Packet.dll"
    carpeta_npcap = system32 / "Npcap"
    dlls = wpcap.is_file() and packet.is_file()
    driver = carpeta_npcap.is_dir()
    if dlls and driver:
        return EstadoNpcap(True, True, "Npcap presente (wpcap.dll, Packet.dll y carpeta Npcap).")
    if dlls:
        return EstadoNpcap(True, dlls,
                           "DLLs de captura presentes, pero no se encontró la carpeta Npcap.")
    return EstadoNpcap(False, False, "No se encontró Npcap (faltan wpcap.dll/Packet.dll).")


@dataclass(frozen=True)
class CapacidadCaptura:
    backend_disponible: bool   # scapy + libpcap/Npcap utilizables.
    detalle: str


def capacidad_captura() -> CapacidadCaptura:
    """Indica si existe un backend de captura utilizable, sin capturar nada."""
    try:
        import scapy  # noqa: F401
    except Exception as error:  # noqa: BLE001
        return CapacidadCaptura(False, f"scapy no disponible: {error}")
    npcap = estado_npcap()
    if not npcap.operativo:
        return CapacidadCaptura(False, f"scapy presente, pero {npcap.detalle}")
    return CapacidadCaptura(True, "scapy + Npcap disponibles para captura pasiva.")


@dataclass
class ObservacionTrafico:
    """Resumen de una captura PASIVA (no se envió nada)."""

    segundos: float
    total: int = 0
    difusion: int = 0
    multidifusion: int = 0
    unicast_propio: int = 0
    unicast_ajeno: int = 0            # Lo decisivo: unicast entre OTROS equipos.
    macs_origen: int = 0
    tipos: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def observa_trafico_ajeno(self) -> bool:
        """True solo si se vio unicast de terceros (posible en un hub o con espejo
        de puerto / modo monitor; falso en una red conmutada normal)."""
        return self.unicast_ajeno > 0


def observar_trafico(ip_interfaz: str, segundos: float = 6.0) -> ObservacionTrafico:
    """Captura PASIVA en la interfaz con la IP dada y clasifica lo observado.

    No envía ni modifica nada: es un ``sniff`` de solo lectura. Requiere Npcap y,
    normalmente, privilegios. Pensado para un laboratorio autorizado.
    """
    resultado = ObservacionTrafico(segundos=segundos)
    try:
        import os
        os.environ.setdefault("SCAPY_USE_LIBPCAP", "yes")
        import warnings
        warnings.filterwarnings("ignore")
        from scapy.all import ARP, Ether, get_working_ifaces, sniff
    except Exception as error:  # noqa: BLE001
        resultado.error = f"No se pudo cargar scapy: {error}"
        return resultado

    iface = next((i for i in get_working_ifaces() if getattr(i, "ip", None) == ip_interfaz), None)
    if iface is None:
        resultado.error = f"No se encontró una interfaz con IP {ip_interfaz}."
        return resultado
    mi_mac = (getattr(iface, "mac", "") or "").lower()
    try:
        paquetes = sniff(iface=iface, timeout=segundos, store=True)   # PASIVO
    except Exception as error:  # noqa: BLE001
        resultado.error = f"La captura falló: {error}"
        return resultado

    macs, tipos = set(), set()
    for p in paquetes:
        if not p.haslayer(Ether):
            continue
        dst = p[Ether].dst.lower()
        src = p[Ether].src.lower()
        macs.add(src)
        tipos.add("ARP" if p.haslayer(ARP) else p.lastlayer().name)
        if dst == _BROADCAST:
            resultado.difusion += 1
        elif dst.startswith(_MCAST_PREFIJOS):
            resultado.multidifusion += 1
        elif mi_mac in (src, dst):
            resultado.unicast_propio += 1
        else:
            resultado.unicast_ajeno += 1
    resultado.total = len(paquetes)
    resultado.macs_origen = len(macs)
    resultado.tipos = sorted(tipos)
    return resultado


@dataclass
class DiagnosticoMotor:
    admin: bool
    npcap: EstadoNpcap
    captura: CapacidadCaptura
    adaptador: str | None
    observacion: ObservacionTrafico | None = None

    @property
    def hay_mecanismo_de_contencion(self) -> bool:
        """True si el equipo cumple los requisitos del motor de envenenamiento
        ARP: administrador, Npcap operativo y una interfaz conectada con IPv4.

        Solo indica que el equipo PUEDE ejecutarlo; la eficacia real depende de la
        topología de la red (DIA/DHCP snooping, otras rutas del objetivo, etc.).
        """
        return self.admin and self.npcap.operativo and self.adaptador is not None


def ejecutar(segundos_observacion: float | None = None) -> DiagnosticoMotor:
    """Reúne el diagnóstico. Con ``segundos_observacion`` añade la captura pasiva."""
    try:
        from infrastructure.network.windows_interfaces import WindowsNetworkInterfaceProvider
        activa = next((i for i in WindowsNetworkInterfaceProvider().list_interfaces()
                       if i.conectada and i.ipv4), None)
    except Exception:  # noqa: BLE001
        activa = None
    observacion = None
    if segundos_observacion and activa and activa.ipv4:
        observacion = observar_trafico(activa.ipv4, segundos_observacion)
    etiqueta = (f"{activa.nombre} ({activa.ipv4}/{activa.prefijo}, gw {activa.puerta_enlace})"
                if activa else None)
    return DiagnosticoMotor(tiene_privilegios_admin(), estado_npcap(), capacidad_captura(),
                            etiqueta, observacion)


def _imprimir(d: DiagnosticoMotor) -> None:
    print("== Diagnóstico del motor de aislamiento (solo lectura) ==")
    print(f"Privilegios de administrador : {'sí' if d.admin else 'no'}")
    print(f"Npcap instalado/operativo    : {'sí' if d.npcap.operativo else 'no'} — {d.npcap.detalle}")
    print(f"Backend de captura           : {'sí' if d.captura.backend_disponible else 'no'} — {d.captura.detalle}")
    print(f"Adaptador en uso             : {d.adaptador or 'no identificado'}")
    o = d.observacion
    if o is not None:
        if o.error:
            print(f"Observación pasiva           : falló — {o.error}")
        else:
            print(f"Observación pasiva ({o.segundos:.0f}s)   : {o.total} paquetes; "
                  f"difusión {o.difusion}, multidifusión {o.multidifusion}, "
                  f"unicast propio {o.unicast_propio}, unicast AJENO {o.unicast_ajeno}; "
                  f"{o.macs_origen} MAC origen; tipos {o.tipos}")
            print(f"¿Observa unicast de terceros? {'sí' if o.observa_trafico_ajeno else 'no'}")
    print(f"¿Requisitos del motor ARP presentes? {'sí' if d.hay_mecanismo_de_contencion else 'no'}")
    if d.hay_mecanismo_de_contencion:
        print("El envenenamiento ARP puede ejecutarse (depende de la topología: DIA/DHCP "
              "snooping y otras rutas del objetivo lo limitan). Uso en laboratorio autorizado.")
    else:
        print("El motor ARP se declara NO DISPONIBLE (faltan administrador, Npcap o interfaz).")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    argv = sys.argv[1:] if argv is None else argv
    segundos = None
    if argv and argv[0] in ("-o", "--observar"):
        segundos = float(argv[1]) if len(argv) > 1 else 6.0
    _imprimir(ejecutar(segundos))
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
