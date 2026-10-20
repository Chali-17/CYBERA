"""Enumeración de interfaces reales mediante Get-NetAdapter / Get-NetIPAddress."""

from __future__ import annotations

from app.models.interfaz_red import InterfazRed, TipoInterfaz
from app.models.mac import es_mac_valida, normalizar_mac
from infrastructure.interfaces import INetworkInterface
from infrastructure.network.powershell import ejecutar_json

# NDIS_PHYSICAL_MEDIUM: 9 = Native 802.11 (Wi-Fi), 14 = 802.3 (Ethernet)
_NDIS_WIFI = 9
_NDIS_ETHERNET = 14

_SCRIPT = r"""
$adaptadores = @(Get-NetAdapter)
$direcciones = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                 Where-Object { $_.AddressState -eq 'Preferred' })
$rutas = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue)
$salida = foreach ($a in $adaptadores) {
    $ip = $direcciones | Where-Object { $_.InterfaceIndex -eq $a.ifIndex } |
          Sort-Object { if ($_.IPAddress -like '169.254.*') { 1 } else { 0 } } |
          Select-Object -First 1
    $gw = $rutas | Where-Object { $_.InterfaceIndex -eq $a.ifIndex } |
          Sort-Object RouteMetric | Select-Object -First 1
    [pscustomobject]@{
        Id           = [string]$a.InterfaceGuid
        Indice       = [int]$a.ifIndex
        Nombre       = [string]$a.Name
        Descripcion  = [string]$a.InterfaceDescription
        Estado       = [string]$a.Status
        Mac          = [string]$a.MacAddress
        NdisMedio    = [int]$a.NdisPhysicalMedium
        Virtual      = [bool]$a.Virtual
        IPv4         = if ($ip) { [string]$ip.IPAddress } else { $null }
        Prefijo      = if ($ip) { [int]$ip.PrefixLength } else { $null }
        PuertaEnlace = if ($gw) { [string]$gw.NextHop } else { $null }
    }
}
ConvertTo-Json -InputObject @($salida) -Compress -Depth 2
"""


def _tipo(ndis: int | None) -> TipoInterfaz:
    if ndis == _NDIS_WIFI:
        return TipoInterfaz.WIFI
    if ndis == _NDIS_ETHERNET:
        return TipoInterfaz.ETHERNET
    return TipoInterfaz.OTRO


def interfaz_desde_registro(r: dict) -> InterfazRed:
    mac = r.get("Mac") or None
    puerta = r.get("PuertaEnlace") or None
    if puerta == "0.0.0.0":
        puerta = None
    return InterfazRed(
        id=str(r["Id"]),
        indice=int(r["Indice"]),
        nombre=str(r.get("Nombre") or r["Id"]),
        descripcion=str(r.get("Descripcion") or ""),
        tipo=_tipo(r.get("NdisMedio")),
        conectada=str(r.get("Estado", "")).lower() == "up",
        mac=normalizar_mac(mac) if mac and es_mac_valida(mac) else None,
        ipv4=r.get("IPv4") or None,
        prefijo=r.get("Prefijo"),
        puerta_enlace=puerta,
        virtual=bool(r.get("Virtual")),
    )


class WindowsNetworkInterfaceProvider(INetworkInterface):
    def __init__(self, ejecutor=ejecutar_json) -> None:
        self._ejecutar = ejecutor

    def list_interfaces(self) -> list[InterfazRed]:
        return [interfaz_desde_registro(r) for r in self._ejecutar(_SCRIPT)]
