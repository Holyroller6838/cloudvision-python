# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Pair-level readiness evaluation. Pure Python; no device I/O."""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from cloudvision.cvlib.actions.ab_upgrade.models import (
    BlockingReason,
    BgpNeighbor,
    BgpPolicy,
    DeviceSnapshot,
    PairCheck,
    ReadinessPolicy,
)


def _check(code: str, ok: bool, message: Optional[str] = None) -> PairCheck:
    return PairCheck(code=code, ok=ok, message=message)


def _block(
    code: str,
    message: str,
    *,
    scope: str = "pair",
    device: Optional[str] = None,
    details: Optional[dict] = None,
) -> BlockingReason:
    return BlockingReason(
        code=code,
        scope=scope,
        message=message,
        device=device,
        details=details or {},
    )


def neighbor_in_bgp_scope(neighbor: BgpNeighbor, policy: BgpPolicy) -> bool:
    """Return True when this neighbor participates in the readiness gate."""
    if neighbor.neighbor in set(policy.ignored_neighbors):
        return False
    if not policy.has_scope_filters():
        return False
    if policy.required_vrfs and neighbor.vrf not in set(policy.required_vrfs):
        return False
    if policy.required_neighbors and neighbor.neighbor not in set(policy.required_neighbors):
        return False
    if policy.required_peer_groups:
        if not neighbor.peer_group or neighbor.peer_group not in set(policy.required_peer_groups):
            return False
    return True


def scoped_bgp_neighbors(snapshot: DeviceSnapshot, policy: BgpPolicy) -> List[BgpNeighbor]:
    return [item for item in snapshot.bgp.neighbors if neighbor_in_bgp_scope(item, policy)]


def _is_up(status: Optional[str]) -> bool:
    return (status or "").lower() == "up"


def _critical_names(snapshot: DeviceSnapshot, policy: ReadinessPolicy) -> List[str]:
    configured = policy.critical_interfaces.get(snapshot.identity.role) or []
    names = [name for name in configured if name]
    if names:
        return names
    if policy.expect_mlag:
        for name in (snapshot.mlag.peer_link, snapshot.mlag.local_interface):
            if name and name not in names:
                names.append(name)
    return names


def _mlag_device_healthy(snapshot: DeviceSnapshot) -> Tuple[bool, List[BlockingReason]]:
    role = snapshot.identity.role
    blockers: List[BlockingReason] = []
    mlag = snapshot.mlag
    if not mlag.enabled:
        blockers.append(
            _block(
                "mlag_not_active",
                f"Device {role} does not have MLAG enabled",
                scope="device",
                device=role,
            )
        )
        return False, blockers
    if (mlag.state or "").lower() != "active":
        blockers.append(
            _block(
                "mlag_not_active",
                f"Device {role} MLAG state is {mlag.state or 'unknown'}",
                scope="device",
                device=role,
                details={"state": mlag.state},
            )
        )
    if not _is_up(mlag.peer_link_status):
        blockers.append(
            _block(
                "mlag_peer_link_down",
                f"Device {role} MLAG peer-link {mlag.peer_link or ''} is "
                f"{mlag.peer_link_status or 'unknown'}",
                scope="device",
                device=role,
                details={
                    "peer_link": mlag.peer_link,
                    "peer_link_status": mlag.peer_link_status,
                },
            )
        )
    sanity = (mlag.config_sanity or "").lower()
    if sanity and sanity != "consistent":
        blockers.append(
            _block(
                "mlag_config_inconsistent",
                f"Device {role} MLAG config-sanity is {sanity}",
                scope="device",
                device=role,
                details={"config_sanity": sanity, "issues": mlag.sanity_issues},
            )
        )
    elif mlag.sanity_issues:
        blockers.append(
            _block(
                "mlag_config_inconsistent",
                f"Device {role} MLAG config-sanity reported issues",
                scope="device",
                device=role,
                details={"issues": mlag.sanity_issues},
            )
        )
    return not blockers, blockers


def evaluate_pair_readiness(
    snapshot_a: DeviceSnapshot,
    snapshot_b: DeviceSnapshot,
    policy: Optional[ReadinessPolicy] = None,
) -> Tuple[bool, List[PairCheck], List[BlockingReason]]:
    """Compare two snapshots and return (ready, checks, blocking_reasons)."""
    policy = policy or ReadinessPolicy()
    checks: List[PairCheck] = []
    blockers: List[BlockingReason] = []

    def add(check: PairCheck, new_blockers: Iterable[BlockingReason] = ()) -> None:
        checks.append(check)
        blockers.extend(list(new_blockers))

    ident_a = snapshot_a.identity
    ident_b = snapshot_b.identity
    identified = bool(ident_a.hostname and ident_b.hostname)
    add(_check("both_identified", identified))
    if not identified:
        blockers.append(
            _block("identity_unresolved", "Could not resolve hostname for both devices")
        )

    same_host = bool(ident_a.hostname and ident_a.hostname == ident_b.hostname)
    same_serial = bool(ident_a.serial and ident_a.serial == ident_b.serial)
    if same_host or same_serial:
        add(
            _check("distinct_devices", False),
            [
                _block(
                    "duplicate_device",
                    "Device A and Device B resolve to the same device",
                    details={
                        "hostname_a": ident_a.hostname,
                        "hostname_b": ident_b.hostname,
                        "serial_a": ident_a.serial,
                        "serial_b": ident_b.serial,
                    },
                )
            ],
        )
    else:
        add(_check("distinct_devices", True))

    reachable = snapshot_a.connectivity.reachable and snapshot_b.connectivity.reachable
    add(_check("both_reachable", reachable))
    for snap in (snapshot_a, snapshot_b):
        if not snap.connectivity.reachable:
            blockers.append(
                _block(
                    "device_unreachable",
                    f"Device {snap.identity.role} is not reachable",
                    scope="device",
                    device=snap.identity.role,
                    details={"error": snap.connectivity.error},
                )
            )

    streaming_reported = any(
        snap.connectivity.streaming_status for snap in (snapshot_a, snapshot_b)
    )
    if streaming_reported:
        streaming_ok = True
        for snap in (snapshot_a, snapshot_b):
            status = snap.connectivity.streaming_status
            if status and status != "ACTIVE":
                streaming_ok = False
                blockers.append(
                    _block(
                        "streaming_inactive",
                        f"Device {snap.identity.role} streaming status is {status}",
                        scope="device",
                        device=snap.identity.role,
                        details={"streaming_status": status},
                    )
                )
        add(_check("both_streaming", streaming_ok))
    else:
        add(_check("both_streaming", True, "inventory overlay not provided"))

    versions_ok = bool(snapshot_a.software.eos_version and snapshot_b.software.eos_version)
    add(_check("both_version_parsed", versions_ok))
    for snap in (snapshot_a, snapshot_b):
        if not snap.software.eos_version:
            blockers.append(
                _block(
                    "version_unparsed",
                    f"Device {snap.identity.role} EOS version could not be parsed",
                    scope="device",
                    device=snap.identity.role,
                )
            )

    if policy.expect_mlag:
        healthy_a, blocks_a = _mlag_device_healthy(snapshot_a)
        healthy_b, blocks_b = _mlag_device_healthy(snapshot_b)
        pair_ok = healthy_a and healthy_b
        pair_blockers = list(blocks_a) + list(blocks_b)
        if (
            snapshot_a.mlag.domain_id
            and snapshot_b.mlag.domain_id
            and snapshot_a.mlag.domain_id != snapshot_b.mlag.domain_id
        ):
            pair_ok = False
            pair_blockers.append(
                _block(
                    "mlag_peer_mismatch",
                    "MLAG domain IDs do not match",
                    details={
                        "domain_a": snapshot_a.mlag.domain_id,
                        "domain_b": snapshot_b.mlag.domain_id,
                    },
                )
            )
        add(_check("mlag_pair_healthy", pair_ok), pair_blockers)
    else:
        add(_check("mlag_pair_healthy", True, "expect_mlag is false"))

    bgp_blockers: List[BlockingReason] = []
    bgp_ok = True
    if policy.bgp.has_scope_filters():
        for snap in (snapshot_a, snapshot_b):
            scoped = scoped_bgp_neighbors(snap, policy.bgp)
            for neighbor in scoped:
                if neighbor.state.lower() != "established":
                    bgp_ok = False
                    bgp_blockers.append(
                        _block(
                            "bgp_neighbor_not_established",
                            f"Device {snap.identity.role} BGP neighbor {neighbor.neighbor} "
                            f"is {neighbor.state}",
                            scope="device",
                            device=snap.identity.role,
                            details=neighbor.to_dict(),
                        )
                    )
        add(_check("bgp_clean", bgp_ok), bgp_blockers)
    else:
        add(_check("bgp_clean", True, "no required BGP neighbors/VRFs/peer-groups"))

    intf_ok = True
    intf_blockers: List[BlockingReason] = []
    for snap in (snapshot_a, snapshot_b):
        names = _critical_names(snap, policy)
        snap.interfaces.critical = {}
        for name in names:
            status = snap.interfaces.statuses.get(name)
            if status is None:
                snap.interfaces.critical[name] = "missing"
                intf_ok = False
                intf_blockers.append(
                    _block(
                        "critical_interface_down",
                        f"Device {snap.identity.role} critical interface {name} was not found",
                        scope="device",
                        device=snap.identity.role,
                        details={"interface": name, "status": "missing"},
                    )
                )
                continue
            snap.interfaces.critical[name] = status
            if status != "up":
                intf_ok = False
                intf_blockers.append(
                    _block(
                        "critical_interface_down",
                        f"Device {snap.identity.role} critical interface {name} is {status}",
                        scope="device",
                        device=snap.identity.role,
                        details={"interface": name, "status": status},
                    )
                )
    add(_check("critical_interfaces_up", intf_ok), intf_blockers)

    ready = all(check.ok for check in checks)
    return ready, checks, blockers
