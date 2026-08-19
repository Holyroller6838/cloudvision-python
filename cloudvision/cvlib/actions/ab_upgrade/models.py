# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""JSON-serializable models for EOS A/B upgrade pair readiness (MVP1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Identity:
    role: str
    queried_as: str
    hostname: Optional[str] = None
    fqdn: Optional[str] = None
    serial: Optional[str] = None
    model: Optional[str] = None
    system_mac: Optional[str] = None
    cv_device_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Connectivity:
    reachable: bool
    cli_ok: bool
    streaming_status: Optional[str] = None
    uptime_seconds: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Software:
    eos_version: Optional[str] = None
    image: Optional[str] = None
    architecture: Optional[str] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Mlag:
    enabled: bool = False
    state: Optional[str] = None
    domain_id: Optional[str] = None
    peer_address: Optional[str] = None
    peer_link: Optional[str] = None
    peer_link_status: Optional[str] = None
    local_interface: Optional[str] = None
    local_interface_status: Optional[str] = None
    config_sanity: Optional[str] = None
    negotiation_status: Optional[str] = None
    sanity_issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BgpNeighbor:
    neighbor: str
    state: str
    vrf: str = "default"
    asn: Optional[str] = None
    peer_group: Optional[str] = None
    prefixes_received: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Bgp:
    enabled: bool = False
    asn: Optional[str] = None
    router_id: Optional[str] = None
    peers_total: int = 0
    peers_established: int = 0
    neighbors: List[BgpNeighbor] = field(default_factory=list)
    peers_not_established: List[BgpNeighbor] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "asn": self.asn,
            "router_id": self.router_id,
            "peers_total": self.peers_total,
            "peers_established": self.peers_established,
            "neighbors": [item.to_dict() for item in self.neighbors],
            "peers_not_established": [item.to_dict() for item in self.peers_not_established],
        }


@dataclass
class Interfaces:
    counts: Dict[str, int] = field(default_factory=lambda: {"up": 0, "down": 0, "total": 0})
    up: List[str] = field(default_factory=list)
    down: List[str] = field(default_factory=list)
    statuses: Dict[str, str] = field(default_factory=dict)
    critical: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DeviceSnapshot:
    identity: Identity
    connectivity: Connectivity
    software: Software
    mlag: Mlag
    bgp: Bgp
    interfaces: Interfaces

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "connectivity": self.connectivity.to_dict(),
            "software": self.software.to_dict(),
            "mlag": self.mlag.to_dict(),
            "bgp": self.bgp.to_dict(),
            "interfaces": self.interfaces.to_dict(),
        }


@dataclass
class PairCheck:
    code: str
    ok: bool
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {"code": self.code, "ok": self.ok}
        if self.message:
            payload["message"] = self.message
        return payload


@dataclass
class BlockingReason:
    code: str
    scope: str
    message: str
    device: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "scope": self.scope,
            "device": self.device,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass
class BgpPolicy:
    required_vrfs: List[str] = field(default_factory=list)
    required_neighbors: List[str] = field(default_factory=list)
    required_peer_groups: List[str] = field(default_factory=list)
    ignored_neighbors: List[str] = field(default_factory=list)
    require_all_established: bool = False

    def has_scope_filters(self) -> bool:
        return bool(
            self.required_vrfs
            or self.required_neighbors
            or self.required_peer_groups
            or self.require_all_established
        )


@dataclass
class ReadinessPolicy:
    expect_mlag: bool = True
    critical_interfaces: Dict[str, List[str]] = field(default_factory=dict)
    bgp: BgpPolicy = field(default_factory=BgpPolicy)
