# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

from cloudvision.cvlib.actions.ab_upgrade.models import (
    Bgp,
    BgpNeighbor,
    BgpPolicy,
    Connectivity,
    DeviceSnapshot,
    Identity,
    Interfaces,
    Mlag,
    ReadinessPolicy,
    Software,
)
from cloudvision.cvlib.actions.ab_upgrade.readiness import (
    evaluate_pair_readiness,
    neighbor_in_bgp_scope,
)


def _snapshot(
    role: str,
    hostname: str,
    serial: str,
    *,
    reachable: bool = True,
    version: str = "4.31.2F",
    mlag_state: str = "active",
    peer_link_status: str = "up",
    idle_bgp: bool = False,
    extra_down: bool = True,
) -> DeviceSnapshot:
    neighbors = [
        BgpNeighbor("192.0.2.11", "Established", vrf="default", peer_group="SPINES"),
        BgpNeighbor(
            "192.0.2.12",
            "Idle" if idle_bgp else "Established",
            vrf="default",
            peer_group="SPINES",
        ),
        BgpNeighbor("192.0.2.254", "Idle", vrf="default", peer_group="UNUSED"),
    ]
    statuses = {
        "Port-Channel2000": peer_link_status if peer_link_status == "up" else "down",
        "Vlan4094": "up",
        "Ethernet48": "down" if extra_down else "up",
    }
    up = [name for name, status in statuses.items() if status == "up"]
    down = [name for name, status in statuses.items() if status != "up"]
    return DeviceSnapshot(
        identity=Identity(role=role, queried_as=hostname, hostname=hostname, serial=serial),
        connectivity=Connectivity(reachable=reachable, cli_ok=reachable),
        software=Software(eos_version=version, source="show_version"),
        mlag=Mlag(
            enabled=True,
            state=mlag_state,
            domain_id="MLAG",
            peer_link="Port-Channel2000",
            peer_link_status=peer_link_status,
            local_interface="Vlan4094",
            local_interface_status="up",
            config_sanity="consistent",
        ),
        bgp=Bgp(
            enabled=True,
            neighbors=neighbors,
            peers_total=len(neighbors),
            peers_established=len([item for item in neighbors if item.state == "Established"]),
            peers_not_established=[item for item in neighbors if item.state != "Established"],
        ),
        interfaces=Interfaces(
            counts={"up": len(up), "down": len(down), "total": len(statuses)},
            up=up,
            down=down,
            statuses=statuses,
        ),
    )


def test_idle_unused_neighbor_does_not_block_without_policy():
    ready, checks, blockers = evaluate_pair_readiness(
        _snapshot("A", "leaf-a", "JPE1"),
        _snapshot("B", "leaf-b", "JPE2"),
        ReadinessPolicy(),
    )
    assert ready is True
    assert blockers == []
    by_code = {item.code: item.ok for item in checks}
    assert by_code["bgp_clean"] is True
    assert by_code["critical_interfaces_up"] is True


def test_required_neighbor_idle_blocks():
    policy = ReadinessPolicy(
        bgp=BgpPolicy(required_neighbors=["192.0.2.12"]),
    )
    ready, _, blockers = evaluate_pair_readiness(
        _snapshot("A", "leaf-a", "JPE1", idle_bgp=True),
        _snapshot("B", "leaf-b", "JPE2"),
        policy,
    )
    assert ready is False
    assert any(item.code == "bgp_neighbor_not_established" for item in blockers)


def test_ignored_neighbor_excluded_from_scope():
    policy = BgpPolicy(
        require_all_established=True,
        ignored_neighbors=["192.0.2.254"],
    )
    neighbor = BgpNeighbor("192.0.2.254", "Idle", vrf="default", peer_group="UNUSED")
    assert neighbor_in_bgp_scope(neighbor, policy) is False
    spine = BgpNeighbor("192.0.2.11", "Established", vrf="default", peer_group="SPINES")
    assert neighbor_in_bgp_scope(spine, policy) is True


def test_unused_down_interface_is_not_a_blocker():
    ready, _, blockers = evaluate_pair_readiness(
        _snapshot("A", "leaf-a", "JPE1", extra_down=True),
        _snapshot("B", "leaf-b", "JPE2", extra_down=True),
        ReadinessPolicy(),
    )
    assert ready is True
    assert blockers == []


def test_mlag_peer_link_down_is_hard_gate():
    ready, _, blockers = evaluate_pair_readiness(
        _snapshot("A", "leaf-a", "JPE1"),
        _snapshot("B", "leaf-b", "JPE2", peer_link_status="down"),
        ReadinessPolicy(expect_mlag=True),
    )
    assert ready is False
    assert any(item.code == "mlag_peer_link_down" for item in blockers)
    assert any(item.code == "critical_interface_down" for item in blockers)
