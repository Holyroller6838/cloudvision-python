# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

from cloudvision.cvlib.actions.ab_upgrade.parsers import (
    parse_bgp,
    parse_interfaces,
    parse_mlag,
    parse_mlag_sanity,
    parse_software,
    structured_payload,
)
from . import fixtures


def test_structured_payload_keeps_eos_json():
    response = {"result": fixtures.version(serial="JPE1", hostname="leaf-a", mac="00:11")}
    payload = structured_payload(response)
    assert isinstance(payload, dict)
    assert payload["version"] == "4.31.2F"
    assert "Software image version" not in str(payload.get("output", ""))


def test_structured_payload_falls_back_to_text_output_only():
    response = {"result": {"output": "Software image version: 4.25.2F\n"}}
    assert structured_payload(response) == "Software image version: 4.25.2F\n"


def test_parse_software_from_json():
    software, extras = parse_software(fixtures.version(serial="JPE1", hostname="leaf-a", mac="aa"))
    assert software.eos_version == "4.31.2F"
    assert software.source == "show_version"
    assert extras["serial"] == "JPE1"


def test_parse_software_text_fallback():
    software, extras = parse_software("Software image version: 4.25.2F\nSerial number: JPE9\n")
    assert software.eos_version == "4.25.2F"
    assert software.source == "show_version_text"
    assert extras["serial"] == "JPE9"


def test_parse_mlag_and_sanity():
    mlag = parse_mlag(fixtures.mlag(peer_address="192.0.2.3"))
    assert mlag.enabled is True
    assert mlag.state == "active"
    assert mlag.peer_link == "Port-Channel2000"
    assert mlag.peer_link_status == "up"
    sanity, issues = parse_mlag_sanity(fixtures.mlag_sanity(False))
    assert sanity == "inconsistent"
    assert issues


def test_parse_mlag_disabled_error():
    mlag = parse_mlag(None, error="% MLAG is disabled")
    assert mlag.enabled is False


def test_parse_bgp_reports_all_neighbors():
    bgp = parse_bgp(fixtures.bgp_summary(idle_neighbor=True))
    assert bgp.enabled is True
    assert bgp.peers_total == 3
    assert bgp.peers_established == 1
    states = {item.neighbor: item.state for item in bgp.neighbors}
    assert states["192.0.2.12"] == "Idle"
    assert states["192.0.2.254"] == "Idle"


def test_parse_interfaces_does_not_require_all_up():
    interfaces = parse_interfaces(fixtures.interfaces(extra_down=True))
    assert "Ethernet48" in interfaces.down
    assert "Port-Channel2000" in interfaces.up
    assert interfaces.counts["down"] >= 1
