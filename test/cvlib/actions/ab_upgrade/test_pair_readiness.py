# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

import json
from typing import Any, Dict, List, Sequence

from cloudvision.cvlib.actions.ab_upgrade.inventory import InventoryRecord, StaticInventory
from cloudvision.cvlib.actions.ab_upgrade.pair_readiness import pair_readiness
from . import fixtures


class FakeCommander:
    """Maps show commands to structured EOS JSON. Never talks to a device."""

    def __init__(self, outputs: Dict[str, Any], exc=None):
        self.outputs = outputs
        self.exc = exc
        self.calls: List[Sequence[Any]] = []
        self.expect_disconnect_flags: List[bool] = []

    def run_commands(self, commands, *, expect_disconnect=False):
        self.calls.append(list(commands))
        self.expect_disconnect_flags.append(expect_disconnect)
        if self.exc:
            raise self.exc
        responses = []
        for command in commands:
            if command == "enable":
                responses.append({"result": {}})
                continue
            spec = self.outputs[command]
            if isinstance(spec, dict) and spec.get("error"):
                responses.append({"error": spec["error"], "result": {}})
            else:
                responses.append({"result": spec})
        return responses


def _ready_commanders():
    cmd_a = FakeCommander(
        fixtures.device_outputs(
            name="leaf-a",
            serial="JPE11111111",
            mac="00:1c:73:00:00:01",
            peer_address="192.0.2.3",
        )
    )
    cmd_b = FakeCommander(
        fixtures.device_outputs(
            name="leaf-b",
            serial="JPE22222222",
            mac="00:1c:73:00:00:02",
            peer_address="192.0.2.2",
        )
    )
    return cmd_a, cmd_b


PARAMS = {
    "device_a": "leaf-a",
    "device_b": "leaf-b",
    "expect_mlag": True,
    "bgp": {
        "required_peer_groups": ["SPINES"],
        "ignored_neighbors": ["192.0.2.254"],
    },
}


def test_ready_pair_returns_ok_and_ready_json():
    cmd_a, cmd_b = _ready_commanders()
    result = pair_readiness(
        cmd_a,
        cmd_b,
        PARAMS,
        inventory=StaticInventory(
            [
                InventoryRecord(
                    device_id="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                    hostname="leaf-a",
                    streaming_status="ACTIVE",
                ),
                InventoryRecord(
                    device_id="BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                    hostname="leaf-b",
                    streaming_status="ACTIVE",
                ),
            ]
        ),
        collected_at="2026-08-19T19:00:00+00:00",
    )
    assert result["ok"] is True
    assert result["data"]["mode"] == "read_only"
    assert result["data"]["pair"]["ready"] is True
    assert result["data"]["blocking_reasons"] == []
    assert result["data"]["devices"]["A"]["software"]["eos_version"] == "4.31.2F"
    assert result["data"]["devices"]["A"]["bgp"]["peers_not_established"]
    # Unused Idle neighbor is reported but ignored by policy.
    idle = [
        item["neighbor"]
        for item in result["data"]["devices"]["A"]["bgp"]["peers_not_established"]
    ]
    assert "192.0.2.254" in idle
    assert "Ethernet48" in result["data"]["devices"]["A"]["interfaces"]["down"]
    json.dumps(result)
    assert ["enable", "reload force"] not in cmd_a.calls
    assert all(flag is False for flag in cmd_a.expect_disconnect_flags)


def test_blocked_pair_keeps_ok_true():
    cmd_a = FakeCommander(
        fixtures.device_outputs(
            name="leaf-a",
            serial="JPE11111111",
            mac="00:1c:73:00:00:01",
            peer_address="192.0.2.3",
            idle_bgp=True,
        )
    )
    cmd_b = FakeCommander(
        fixtures.device_outputs(
            name="leaf-b",
            serial="JPE22222222",
            mac="00:1c:73:00:00:02",
            peer_address="192.0.2.2",
            peer_link_up=False,
        )
    )
    result = pair_readiness(cmd_a, cmd_b, PARAMS, collected_at="2026-08-19T19:00:00+00:00")
    assert result["ok"] is True
    assert result["data"]["pair"]["ready"] is False
    codes = {item["code"] for item in result["data"]["blocking_reasons"]}
    assert "bgp_neighbor_not_established" in codes
    assert "mlag_peer_link_down" in codes
    json.dumps(result)


def test_unreachable_device_is_operational_block_not_action_failure():
    cmd_a, _ = _ready_commanders()
    cmd_b = FakeCommander({}, exc=ConnectionError("offline"))
    result = pair_readiness(cmd_a, cmd_b, PARAMS)
    assert result["ok"] is True
    assert result["data"]["pair"]["ready"] is False
    assert result["data"]["devices"]["B"]["connectivity"]["reachable"] is False
    codes = {item["code"] for item in result["data"]["blocking_reasons"]}
    assert "device_unreachable" in codes


def test_missing_device_params_are_action_failures():
    cmd_a, cmd_b = _ready_commanders()
    result = pair_readiness(cmd_a, cmd_b, {"device_a": "leaf-a"})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert cmd_a.calls == []


def test_mvp1_never_sends_write_commands():
    cmd_a, cmd_b = _ready_commanders()
    pair_readiness(cmd_a, cmd_b, PARAMS)
    sent = [cmd for call in cmd_a.calls + cmd_b.calls for cmd in call]
    assert all(cmd == "enable" or str(cmd).startswith("show ") for cmd in sent)
    assert "reload force" not in sent
    assert "configure terminal" not in sent
    assert "boot system flash:EOS.swi" not in sent
