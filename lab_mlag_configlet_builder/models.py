"""Input models for the lab MLAG configlet builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent
    yaml = None  # type: ignore[assignment]


class InputError(ValueError):
    """Raised when MLAG builder inputs are invalid."""


@dataclass(frozen=True)
class PeerLink:
    """Dedicated MLAG peer-link Port-Channel and members."""

    port_channel: str
    members: Sequence[str]
    trunk_group: str = "mlagpeer"

    def __post_init__(self) -> None:
        if not self.port_channel:
            raise InputError("peer_link.port_channel is required")
        if not self.members:
            raise InputError("peer_link.members must list at least one interface")
        object.__setattr__(self, "members", tuple(self.members))


@dataclass(frozen=True)
class DownstreamPortChannel:
    """Downstream LACP Port-Channel dual-homed via MLAG."""

    port_channel: str
    members: Sequence[str]
    mlag_id: int
    description: str = "Downstream LACP"
    switchport_mode: str = "trunk"
    trunk_allowed_vlans: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.port_channel:
            raise InputError("downstream.port_channel is required")
        if not self.members:
            raise InputError("downstream.members must list at least one interface")
        if not isinstance(self.mlag_id, int) or self.mlag_id < 1 or self.mlag_id > 2000:
            raise InputError("downstream.mlag_id must be an integer between 1 and 2000")
        mode = self.switchport_mode.lower()
        if mode not in {"trunk", "access"}:
            raise InputError("downstream.switchport_mode must be 'trunk' or 'access'")
        object.__setattr__(self, "members", tuple(self.members))
        object.__setattr__(self, "switchport_mode", mode)


@dataclass(frozen=True)
class DeviceMlagParams:
    """Per-device MLAG addressing and identity."""

    hostname: str
    peer_svi_ip: str
    peer_address: str
    mlag_id: Optional[int] = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.hostname:
            raise InputError("device hostname is required")
        if not self.peer_svi_ip:
            raise InputError(f"{self.hostname}: peer_svi_ip is required")
        if not self.peer_address:
            raise InputError(f"{self.hostname}: peer_address is required")
        if "/" not in self.peer_svi_ip:
            raise InputError(
                f"{self.hostname}: peer_svi_ip must include a prefix length "
                f"(e.g. 10.255.255.1/30), got {self.peer_svi_ip!r}"
            )


@dataclass(frozen=True)
class MlagLabInputs:
    """Shared + per-device inputs for LAB01 MLAG configlets."""

    domain_id: str
    devices: Mapping[str, DeviceMlagParams]
    peer_link: PeerLink
    downstream: DownstreamPortChannel
    peer_vlan: int = 4094
    peer_vlan_name: str = "MLAG_PEER"
    peer_link_description: str = "MLAG Peer Link"

    def __post_init__(self) -> None:
        if not self.domain_id:
            raise InputError("domain_id is required")
        if self.peer_vlan < 1 or self.peer_vlan > 4094:
            raise InputError("peer_vlan must be between 1 and 4094")
        if len(self.devices) < 2:
            raise InputError("at least two devices are required for MLAG")
        object.__setattr__(self, "devices", dict(self.devices))

    def require_device(self, hostname: str) -> DeviceMlagParams:
        try:
            return self.devices[hostname]
        except KeyError as exc:
            known = ", ".join(sorted(self.devices))
            raise InputError(f"unknown device {hostname!r}; known: {known}") from exc


def _require_mapping(data: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise InputError(f"{label} must be a mapping")
    return data


def _require_list(data: Any, label: str) -> List[Any]:
    if not isinstance(data, list) or not data:
        raise InputError(f"{label} must be a non-empty list")
    return data


def parse_inputs(raw: Mapping[str, Any]) -> MlagLabInputs:
    """Parse a raw mapping (e.g. YAML) into validated MlagLabInputs."""
    data = _require_mapping(raw, "root")

    peer_link_raw = _require_mapping(data.get("peer_link"), "peer_link")
    peer_link = PeerLink(
        port_channel=str(peer_link_raw.get("port_channel", "")).strip(),
        members=[str(m).strip() for m in _require_list(peer_link_raw.get("members"), "peer_link.members")],
        trunk_group=str(peer_link_raw.get("trunk_group", "mlagpeer")).strip() or "mlagpeer",
    )

    downstream_raw = _require_mapping(data.get("downstream"), "downstream")
    downstream = DownstreamPortChannel(
        port_channel=str(downstream_raw.get("port_channel", "")).strip(),
        members=[
            str(m).strip() for m in _require_list(downstream_raw.get("members"), "downstream.members")
        ],
        mlag_id=int(downstream_raw["mlag_id"]),
        description=str(downstream_raw.get("description", "Downstream LACP")).strip()
        or "Downstream LACP",
        switchport_mode=str(downstream_raw.get("switchport_mode", "trunk")).strip() or "trunk",
        trunk_allowed_vlans=(
            str(downstream_raw["trunk_allowed_vlans"]).strip()
            if downstream_raw.get("trunk_allowed_vlans") is not None
            else None
        ),
    )

    devices_raw = _require_mapping(data.get("devices"), "devices")
    devices: Dict[str, DeviceMlagParams] = {}
    for hostname, device_raw in devices_raw.items():
        device_map = _require_mapping(device_raw, f"devices.{hostname}")
        mlag_id = device_map.get("mlag_id")
        devices[str(hostname)] = DeviceMlagParams(
            hostname=str(hostname),
            peer_svi_ip=str(device_map.get("peer_svi_ip", "")).strip(),
            peer_address=str(device_map.get("peer_address", "")).strip(),
            mlag_id=int(mlag_id) if mlag_id is not None else None,
            description=str(device_map.get("description", "")).strip(),
        )

    return MlagLabInputs(
        domain_id=str(data.get("domain_id", "")).strip(),
        peer_vlan=int(data.get("peer_vlan", 4094)),
        peer_vlan_name=str(data.get("peer_vlan_name", "MLAG_PEER")).strip() or "MLAG_PEER",
        peer_link_description=str(data.get("peer_link_description", "MLAG Peer Link")).strip()
        or "MLAG Peer Link",
        peer_link=peer_link,
        downstream=downstream,
        devices=devices,
    )


def load_inputs(path: str | Path) -> MlagLabInputs:
    """Load and validate MLAG inputs from a YAML file."""
    if yaml is None:
        raise InputError(
            "PyYAML is required to load YAML inputs. Install with: pip install pyyaml"
        )
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, Mapping):
        raise InputError(f"{input_path}: root document must be a mapping")
    return parse_inputs(raw)
