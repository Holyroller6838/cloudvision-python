# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Fixture EOS JSON for A/B pair-readiness unit tests. No live device data."""

from typing import Any, Dict


def hostname(name: str, domain: str = "dc.example.com") -> Dict[str, Any]:
    return {"hostname": name, "fqdn": f"{name}.{domain}"}


def version(
    *,
    ver: str = "4.31.2F",
    serial: str,
    hostname: str,
    mac: str,
    uptime: float = 184221.0,
) -> Dict[str, Any]:
    return {
        "modelName": "DCS-7050CX3-32S",
        "version": ver,
        "image": f"EOS-{ver}.swi",
        "architecture": "x86_64",
        "serialNumber": serial,
        "systemMacAddress": mac,
        "hostname": hostname,
        "uptime": uptime,
    }


def mlag(*, peer_address: str, peer_link_status: str = "up") -> Dict[str, Any]:
    return {
        "domainId": "MLAG",
        "localInterface": "Vlan4094",
        "peerAddress": peer_address,
        "peerLink": "Port-Channel2000",
        "peerLinkStatus": peer_link_status,
        "localIntStatus": "up",
        "state": "active",
        "negotiationStatus": "connected",
        "configSanity": "consistent",
        "systemId": "00:1c:73:aa:00:01",
    }


def mlag_sanity(consistent: bool = True) -> Dict[str, Any]:
    if consistent:
        return {"mlagSanityChecks": [], "configSanity": "consistent"}
    return {
        "configSanity": "inconsistent",
        "mlagSanityChecks": [
            {"result": "inconsistent", "detail": "Peer-link VLAN mismatch"},
        ],
    }


def bgp_summary(*, idle_neighbor: bool = False) -> Dict[str, Any]:
    peers = {
        "192.0.2.11": {
            "peerState": "Established",
            "prefixReceived": 48,
            "asn": "65000",
            "peerGroup": "SPINES",
        },
        "192.0.2.12": {
            "peerState": "Idle" if idle_neighbor else "Established",
            "prefixReceived": 0 if idle_neighbor else 48,
            "asn": "65000",
            "peerGroup": "SPINES",
        },
        "192.0.2.254": {
            "peerState": "Idle",
            "prefixReceived": 0,
            "asn": "65099",
            "peerGroup": "UNUSED",
        },
    }
    return {
        "vrfs": {
            "default": {
                "routerId": "192.0.2.1",
                "asn": "65001",
                "peers": peers,
            }
        }
    }


def interfaces(*, peer_link_up: bool = True, extra_down: bool = True) -> Dict[str, Any]:
    statuses = {
        "Ethernet1": {
            "linkStatus": "connected",
            "lineProtocolStatus": "up",
            "description": "peer-link member",
        },
        "Management0": {
            "linkStatus": "connected",
            "lineProtocolStatus": "up",
        },
        "Port-Channel2000": {
            "linkStatus": "connected" if peer_link_up else "notconnect",
            "lineProtocolStatus": "up" if peer_link_up else "down",
        },
        "Vlan4094": {
            "linkStatus": "connected",
            "lineProtocolStatus": "up",
        },
    }
    if extra_down:
        statuses["Ethernet48"] = {
            "linkStatus": "notconnect",
            "lineProtocolStatus": "down",
            "description": "unused access port",
        }
    return {"interfaceStatuses": statuses}


def device_outputs(
    *,
    name: str,
    serial: str,
    mac: str,
    peer_address: str,
    idle_bgp: bool = False,
    peer_link_up: bool = True,
    extra_down: bool = True,
) -> Dict[str, Any]:
    return {
        "show hostname": hostname(name),
        "show version": version(serial=serial, hostname=name, mac=mac),
        "show mlag": mlag(
            peer_address=peer_address,
            peer_link_status="up" if peer_link_up else "down",
        ),
        "show mlag config-sanity": mlag_sanity(True),
        "show ip bgp summary": bgp_summary(idle_neighbor=idle_bgp),
        "show interfaces status": interfaces(peer_link_up=peer_link_up, extra_down=extra_down),
    }
