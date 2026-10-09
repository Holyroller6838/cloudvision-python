"""Offline validation tests for the lab MLAG configlet builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_mlag_configlet_builder.builder import MlagConfigletBuilder, build_configlets_from_file
from lab_mlag_configlet_builder.models import InputError, load_inputs, parse_inputs
from lab_mlag_configlet_builder.safety import SafetyError, assert_safe_eos_config

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = PACKAGE_ROOT / "samples"
INPUTS = SAMPLES / "lab01_inputs.yaml"
EXPECTED = SAMPLES / "expected"


def test_sample_inputs_load_lab01_pair() -> None:
    inputs = load_inputs(INPUTS)
    assert inputs.domain_id == "LAB01"
    assert inputs.peer_vlan == 4094
    assert set(inputs.devices) == {"LAB01A", "LAB01B"}
    assert inputs.devices["LAB01A"].peer_address == "10.255.255.2"
    assert inputs.devices["LAB01B"].peer_svi_ip == "10.255.255.2/30"
    assert inputs.downstream.mlag_id == 20


@pytest.mark.parametrize("hostname", ["LAB01A", "LAB01B"])
def test_generated_config_matches_expected(hostname: str) -> None:
    expected = (EXPECTED / f"{hostname}.cfg").read_text(encoding="utf-8")
    actual = build_configlets_from_file(INPUTS, devices=[hostname])[hostname]
    assert actual == expected


def test_build_all_returns_both_devices() -> None:
    configlets = build_configlets_from_file(INPUTS)
    assert set(configlets) == {"LAB01A", "LAB01B"}
    assert "peer-address 10.255.255.2" in configlets["LAB01A"]
    assert "peer-address 10.255.255.1" in configlets["LAB01B"]
    assert "ip address 10.255.255.1/30" in configlets["LAB01A"]
    assert "ip address 10.255.255.2/30" in configlets["LAB01B"]


def test_config_contains_required_mlag_elements() -> None:
    config = build_configlets_from_file(INPUTS, devices=["LAB01A"])["LAB01A"]
    required = [
        "vlan 4094",
        "trunk group mlagpeer",
        "interface Port-Channel10",
        "channel-group 10 mode active",
        "interface Vlan4094",
        "mlag configuration",
        "domain-id LAB01",
        "local-interface Vlan4094",
        "peer-link Port-Channel10",
        "interface Port-Channel20",
        "mlag 20",
        "channel-group 20 mode active",
    ]
    for snippet in required:
        assert snippet in config


def test_output_is_safe_additive_eos() -> None:
    for hostname, config in build_configlets_from_file(INPUTS).items():
        assert_safe_eos_config(config)
        lowered = config.lower()
        assert "default interface" not in lowered
        assert "write erase" not in lowered
        assert "interface management" not in lowered
        assert "no interface" not in lowered
        assert "no vlan" not in lowered


def test_rejects_management_interface_in_inputs() -> None:
    raw = load_inputs(INPUTS)
    bad = parse_inputs(
        {
            "domain_id": raw.domain_id,
            "peer_vlan": raw.peer_vlan,
            "peer_link": {
                "port_channel": "Port-Channel10",
                "members": ["Management1"],
                "trunk_group": "mlagpeer",
            },
            "downstream": {
                "port_channel": "Port-Channel20",
                "members": ["Ethernet1"],
                "mlag_id": 20,
            },
            "devices": {
                name: {
                    "peer_svi_ip": dev.peer_svi_ip,
                    "peer_address": dev.peer_address,
                }
                for name, dev in raw.devices.items()
            },
        }
    )
    with pytest.raises(SafetyError, match="management interface"):
        MlagConfigletBuilder(bad)


def test_safety_rejects_destructive_config() -> None:
    with pytest.raises(SafetyError):
        assert_safe_eos_config("default interface Ethernet1\n")
    with pytest.raises(SafetyError):
        assert_safe_eos_config("interface Management1\n   ip address 1.2.3.4/24\n")
    with pytest.raises(SafetyError):
        assert_safe_eos_config("no vlan 4094\n")


def test_configurable_overrides() -> None:
    inputs = parse_inputs(
        {
            "domain_id": "CUSTOM_DOMAIN",
            "peer_vlan": 4000,
            "peer_link": {
                "port_channel": "Port-Channel100",
                "members": ["Ethernet3", "Ethernet4"],
                "trunk_group": "peertrunk",
            },
            "downstream": {
                "port_channel": "Po30",
                "members": ["Ethernet5"],
                "mlag_id": 30,
                "switchport_mode": "access",
            },
            "devices": {
                "LAB01A": {
                    "peer_svi_ip": "192.0.2.1/30",
                    "peer_address": "192.0.2.2",
                    "mlag_id": 30,
                },
                "LAB01B": {
                    "peer_svi_ip": "192.0.2.2/30",
                    "peer_address": "192.0.2.1",
                },
            },
        }
    )
    config = MlagConfigletBuilder(inputs).build("LAB01A")
    assert "domain-id CUSTOM_DOMAIN" in config
    assert "vlan 4000" in config
    assert "interface Port-Channel100" in config
    assert "channel-group 100 mode active" in config
    assert "trunk group peertrunk" in config
    assert "interface Port-Channel30" in config
    assert "mlag 30" in config
    assert "switchport mode access" in config
    assert "ip address 192.0.2.1/30" in config
    assert_safe_eos_config(config)


def test_unknown_device_raises() -> None:
    builder = MlagConfigletBuilder(load_inputs(INPUTS))
    with pytest.raises(InputError, match="unknown device"):
        builder.build("LAB99Z")


def test_peer_svi_requires_prefix() -> None:
    with pytest.raises(InputError, match="prefix length"):
        parse_inputs(
            {
                "domain_id": "LAB01",
                "peer_link": {
                    "port_channel": "Port-Channel10",
                    "members": ["Ethernet49"],
                },
                "downstream": {
                    "port_channel": "Port-Channel20",
                    "members": ["Ethernet1"],
                    "mlag_id": 20,
                },
                "devices": {
                    "LAB01A": {"peer_svi_ip": "10.255.255.1", "peer_address": "10.255.255.2"},
                    "LAB01B": {"peer_svi_ip": "10.255.255.2/30", "peer_address": "10.255.255.1"},
                },
            }
        )


def test_cli_stdout_is_eos_only(capsys: pytest.CaptureFixture[str]) -> None:
    from lab_mlag_configlet_builder.cli import main

    rc = main(["--inputs", str(INPUTS), "--device", "LAB01A"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out == (EXPECTED / "LAB01A.cfg").read_text(encoding="utf-8")
    assert_safe_eos_config(out)
