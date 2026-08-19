# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Normalize EOS JSON (and text fallback) into MVP1 models."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from cloudvision.cvlib.actions.ab_upgrade.models import (
    Bgp,
    BgpNeighbor,
    Connectivity,
    Identity,
    Interfaces,
    Mlag,
    Software,
)
from cloudvision.cvlib.actions.commander import first_command_error

Command = Union[str, Dict[str, Any]]

_SOFTWARE_VERSION_RE = re.compile(r"Software image version:\s*(\S+)", re.IGNORECASE)
_SERIAL_RE = re.compile(r"Serial number:\s*(\S+)", re.IGNORECASE)
_MODEL_RE = re.compile(r"(?:Hardware model|Model name):\s*(\S+)", re.IGNORECASE)
_ARCH_RE = re.compile(r"Architecture:\s*(\S+)", re.IGNORECASE)
_MAC_RE = re.compile(r"System MAC address:\s*(\S+)", re.IGNORECASE)
_UP_KEYS = {"up", "connected", "linkup", "link-up"}
_DOWN_HINTS = ("down", "notconnect", "notcon", "disabled", "errdisabled", "lowerlayerdown")


def structured_payload(response: Mapping[str, Any]) -> Any:
    """Prefer structured EOS JSON from runDeviceCmds(fmt='json').

    Text is returned only when the transport wrapped a transcript in
    ``{"output": "..."}`` (or equivalent) with no structured keys.
    """
    result = response.get("result")
    if isinstance(result, dict):
        structured_keys = set(result) - {"output", "response", "stdout"}
        if structured_keys:
            return result
        for key in ("output", "response", "stdout"):
            value = result.get(key)
            if isinstance(value, str):
                return value
        return result
    if isinstance(result, str):
        return result
    for key in ("output", "response", "stdout"):
        value = response.get(key)
        if isinstance(value, str):
            return value
    return result


def last_show_payload(
    commands: Sequence[Command],
    responses: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[str], Any, Optional[str]]:
    """Return (command, payload, error) for the last non-enable command."""
    error = first_command_error(responses)
    paired = list(zip(list(commands), list(responses)))
    for command, response in reversed(paired):
        text = command if isinstance(command, str) else str(command.get("cmd", command))
        if str(text).strip().lower() == "enable":
            continue
        payload = structured_payload(response)
        return str(text), payload, error
    if paired:
        return None, structured_payload(paired[-1][1]), error
    return None, None, error


def _as_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_hostname(payload: Any) -> Dict[str, Optional[str]]:
    if isinstance(payload, Mapping):
        return {
            "hostname": _as_str(payload.get("hostname") or payload.get("hostName")),
            "fqdn": _as_str(payload.get("fqdn") or payload.get("FQDN")),
        }
    if isinstance(payload, str):
        hostname = None
        fqdn = None
        for line in payload.splitlines():
            lower = line.lower()
            if lower.startswith("hostname:"):
                hostname = line.split(":", 1)[1].strip()
            elif "fqdn" in lower and ":" in line:
                fqdn = line.split(":", 1)[1].strip()
            elif not hostname and line.strip() and " " not in line.strip():
                hostname = line.strip()
        return {"hostname": hostname, "fqdn": fqdn}
    return {"hostname": None, "fqdn": None}


def parse_software(payload: Any) -> Tuple[Software, Dict[str, Any]]:
    """Return software facts plus extra identity fields from show version."""
    extras: Dict[str, Any] = {}
    software = Software()
    if isinstance(payload, Mapping):
        version = payload.get("version") or payload.get("softwareImageVersion")
        software.eos_version = _as_str(version)
        software.image = _as_str(payload.get("image") or payload.get("softwareImage"))
        software.architecture = _as_str(payload.get("architecture"))
        software.source = "show_version" if software.eos_version else None
        extras["serial"] = _as_str(payload.get("serialNumber") or payload.get("serial_number"))
        extras["model"] = _as_str(payload.get("modelName") or payload.get("model_name"))
        extras["system_mac"] = _as_str(
            payload.get("systemMacAddress") or payload.get("system_mac_address")
        )
        extras["uptime_seconds"] = _as_float(payload.get("uptime"))
        extras["hostname"] = _as_str(payload.get("hostname"))
        extras["fqdn"] = _as_str(payload.get("fqdn"))
        return software, extras
    if isinstance(payload, str):
        match = _SOFTWARE_VERSION_RE.search(payload)
        software.eos_version = match.group(1).rstrip(",") if match else None
        software.source = "show_version_text" if software.eos_version else None
        arch = _ARCH_RE.search(payload)
        software.architecture = arch.group(1) if arch else None
        serial = _SERIAL_RE.search(payload)
        extras["serial"] = serial.group(1) if serial else None
        model = _MODEL_RE.search(payload)
        extras["model"] = model.group(1) if model else None
        mac = _MAC_RE.search(payload)
        extras["system_mac"] = mac.group(1) if mac else None
        return software, extras
    return software, extras


def _normalize_status(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    compact = value.replace(" ", "").replace("_", "").replace("-", "").lower()
    if compact in {item.replace("-", "") for item in _UP_KEYS}:
        return "up"
    if any(hint in compact for hint in _DOWN_HINTS):
        return "down"
    return value.lower()


def _error_means_disabled(error: Optional[str]) -> bool:
    if not error:
        return False
    lowered = error.lower()
    return "disabled" in lowered or "not enabled" in lowered or "no such" in lowered


def _mlag_field(payload: str, label: str) -> Optional[str]:
    match = re.search(rf"{label}\s*:\s*(\S+)", payload, re.IGNORECASE)
    return match.group(1) if match else None


def parse_mlag(payload: Any, error: Optional[str] = None) -> Mlag:
    if error and _error_means_disabled(error):
        return Mlag(enabled=False, state="disabled")
    if isinstance(payload, Mapping):
        domain = _as_str(payload.get("domainId") or payload.get("domain_id"))
        state = _as_str(payload.get("state"))
        enabled = bool(domain) or (
            state is not None and state.lower() not in ("disabled", "none")
        )
        sanity = _as_str(payload.get("configSanity") or payload.get("config_sanity"))
        return Mlag(
            enabled=enabled,
            state=state,
            domain_id=domain,
            peer_address=_as_str(payload.get("peerAddress") or payload.get("peer_address")),
            peer_link=_as_str(payload.get("peerLink") or payload.get("peer_link")),
            peer_link_status=_normalize_status(
                _as_str(payload.get("peerLinkStatus") or payload.get("peer_link_status"))
            ),
            local_interface=_as_str(
                payload.get("localInterface") or payload.get("local_interface")
            ),
            local_interface_status=_normalize_status(
                _as_str(payload.get("localIntStatus") or payload.get("local_interface_status"))
            ),
            config_sanity=sanity.lower() if sanity else None,
            negotiation_status=_as_str(
                payload.get("negotiationStatus") or payload.get("negotiation_status")
            ),
        )
    if isinstance(payload, str):
        if "mlag is disabled" in payload.lower():
            return Mlag(enabled=False, state="disabled")
        domain = _mlag_field(payload, "domain id") or _mlag_field(payload, "mlag domain")
        sanity = _mlag_field(payload, "config-sanity") or _mlag_field(
            payload, "configuration sanity"
        )
        return Mlag(
            enabled=bool(domain),
            state=_mlag_field(payload, "state"),
            domain_id=domain,
            peer_address=_mlag_field(payload, "peer address"),
            peer_link=_mlag_field(payload, "peer link"),
            peer_link_status=_normalize_status(_mlag_field(payload, "peer link status")),
            local_interface=_mlag_field(payload, "local interface"),
            local_interface_status=_normalize_status(
                _mlag_field(payload, "local interface status")
            ),
            config_sanity=sanity.lower() if sanity else None,
        )
    if error:
        return Mlag(enabled=False, state="unknown")
    return Mlag(enabled=False)


def parse_mlag_sanity(payload: Any, error: Optional[str] = None) -> Tuple[Optional[str], List[str]]:
    if error:
        return None, [error]
    issues: List[str] = []
    if isinstance(payload, Mapping):
        for key in ("mlagSanityChecks", "globalConfiguration", "interfaceConfiguration", "checks"):
            value = payload.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, Mapping):
                    result = str(item.get("result") or item.get("status") or "").lower()
                    detail = _as_str(item.get("detail") or item.get("message") or item)
                    if result and result not in ("consistent", "ok", "pass", "passed"):
                        issues.append(detail or result)
                    elif not result and detail:
                        issues.append(detail)
                elif item:
                    issues.append(str(item))
        if payload.get("configSanity"):
            return str(payload.get("configSanity")).lower(), issues
        return ("inconsistent" if issues else "consistent"), issues
    if isinstance(payload, str):
        if "inconsistent" in payload.lower():
            return "inconsistent", [line.strip() for line in payload.splitlines() if line.strip()]
        return "consistent", []
    return None, []


def parse_bgp(payload: Any, error: Optional[str] = None) -> Bgp:
    if error and _error_means_disabled(error):
        return Bgp(enabled=False)
    if isinstance(payload, Mapping):
        vrfs = payload.get("vrfs")
        if not isinstance(vrfs, Mapping):
            if "peers" in payload:
                vrfs = {"default": payload}
            else:
                return Bgp(enabled=False)
        neighbors: List[BgpNeighbor] = []
        asn = None
        router_id = None
        for vrf_name, vrf_data in vrfs.items():
            if not isinstance(vrf_data, Mapping):
                continue
            if asn is None:
                asn = _as_str(vrf_data.get("asn") or vrf_data.get("as"))
            if router_id is None:
                router_id = _as_str(vrf_data.get("routerId") or vrf_data.get("router_id"))
            peers = vrf_data.get("peers") or vrf_data.get("peersStatus") or {}
            if not isinstance(peers, Mapping):
                continue
            for neighbor, peer in peers.items():
                if not isinstance(peer, Mapping):
                    continue
                state = _as_str(peer.get("peerState") or peer.get("state")) or "unknown"
                neighbors.append(
                    BgpNeighbor(
                        neighbor=str(neighbor),
                        state=state,
                        vrf=str(vrf_name),
                        asn=_as_str(peer.get("asn") or peer.get("peerAs")),
                        peer_group=_as_str(peer.get("peerGroup") or peer.get("peer_group")),
                        prefixes_received=_as_int(
                            peer.get("prefixReceived") or peer.get("prefixesReceived")
                        ),
                    )
                )
        established = [item for item in neighbors if item.state.lower() == "established"]
        not_established = [item for item in neighbors if item.state.lower() != "established"]
        return Bgp(
            enabled=True,
            asn=asn,
            router_id=router_id,
            peers_total=len(neighbors),
            peers_established=len(established),
            neighbors=neighbors,
            peers_not_established=not_established,
        )
    if isinstance(payload, str) and "bgp is disabled" in payload.lower():
        return Bgp(enabled=False)
    if error:
        return Bgp(enabled=False)
    return Bgp(enabled=False)


def parse_interfaces(payload: Any) -> Interfaces:
    statuses: Dict[str, str] = {}
    if isinstance(payload, Mapping):
        raw = (
            payload.get("interfaceStatuses")
            or payload.get("interfaceStatus")
            or payload.get("interfaces")
            or payload
        )
        if isinstance(raw, Mapping):
            for name, data in raw.items():
                if name in ("interfaceStatuses", "vrfs"):
                    continue
                if isinstance(data, Mapping):
                    link = _as_str(
                        data.get("linkStatus")
                        or data.get("lineProtocolStatus")
                        or data.get("operStatus")
                        or data.get("status")
                    )
                    line = _as_str(data.get("lineProtocolStatus"))
                    link_status = _normalize_status(link)
                    line_status = _normalize_status(line) if line else "up"
                    if link_status == "up" and line_status != "up":
                        statuses[str(name)] = "down"
                    else:
                        statuses[str(name)] = link_status
                elif isinstance(data, str):
                    statuses[str(name)] = _normalize_status(data)
    up = sorted(name for name, status in statuses.items() if status == "up")
    down = sorted(name for name, status in statuses.items() if status != "up")
    return Interfaces(
        counts={"up": len(up), "down": len(down), "total": len(statuses)},
        up=up,
        down=down,
        statuses=statuses,
    )


def parse_identity(
    role: str,
    queried_as: str,
    hostname_payload: Any,
    version_extras: Mapping[str, Any],
) -> Identity:
    host = parse_hostname(hostname_payload)
    return Identity(
        role=role,
        queried_as=queried_as,
        hostname=host.get("hostname") or _as_str(version_extras.get("hostname")) or queried_as,
        fqdn=host.get("fqdn") or _as_str(version_extras.get("fqdn")),
        serial=_as_str(version_extras.get("serial")),
        model=_as_str(version_extras.get("model")),
        system_mac=_as_str(version_extras.get("system_mac")),
    )


def parse_connectivity(
    *,
    reachable: bool,
    cli_ok: bool,
    uptime_seconds: Optional[float] = None,
    streaming_status: Optional[str] = None,
    error: Optional[str] = None,
) -> Connectivity:
    return Connectivity(
        reachable=reachable,
        cli_ok=cli_ok,
        streaming_status=streaming_status,
        uptime_seconds=uptime_seconds,
        error=error,
    )
