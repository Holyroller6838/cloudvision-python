# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

from typing import Any, List, Sequence

import pytest

from cloudvision.cvlib.actions.ab_upgrade.readonly import (
    ReadOnlyCommander,
    validate_readonly_commands,
)
from cloudvision.cvlib.actions.safe import WorkflowActionError


class RecordingCommander:
    def __init__(self):
        self.calls: List[Sequence[Any]] = []
        self.expect_disconnect_flags: List[bool] = []

    def run_commands(self, commands, *, expect_disconnect=False):
        self.calls.append(list(commands))
        self.expect_disconnect_flags.append(expect_disconnect)
        return [{"result": {}} for _ in commands]


WRITE_COMMANDS = [
    "configure terminal",
    "conf t",
    "boot system flash:EOS.swi",
    "reload force",
    "reload",
    "write memory",
    "write",
    "copy running-config startup-config",
    "delete flash:EOS.swi",
    "install source flash:EOS.swi",
    "bash ls",
    "erase startup-config",
]


@pytest.mark.parametrize("command", WRITE_COMMANDS)
def test_validate_rejects_write_commands(command):
    with pytest.raises(WorkflowActionError) as exc_info:
        validate_readonly_commands(["enable", command])
    assert exc_info.value.code == "write_rejected"


def test_validate_rejects_interactive_input():
    with pytest.raises(WorkflowActionError) as exc_info:
        validate_readonly_commands(
            [{"cmd": "copy terminal: file:flash:token", "input": "secret"}]
        )
    assert exc_info.value.code == "write_rejected"
    assert "Interactive" in exc_info.value.message


def test_validate_allows_enable_and_show():
    validate_readonly_commands(["enable", "show version"])
    validate_readonly_commands(["show ip bgp summary"])
    validate_readonly_commands(["show mlag config-sanity"])


def test_readonly_commander_does_not_execute_write_commands():
    inner = RecordingCommander()
    wrapped = ReadOnlyCommander(inner)
    with pytest.raises(WorkflowActionError) as exc_info:
        wrapped.run_commands(["enable", "reload force"])
    assert exc_info.value.code == "write_rejected"
    assert inner.calls == []


def test_readonly_commander_does_not_execute_expect_disconnect():
    inner = RecordingCommander()
    wrapped = ReadOnlyCommander(inner)
    with pytest.raises(WorkflowActionError) as exc_info:
        wrapped.run_commands(["enable", "show version"], expect_disconnect=True)
    assert exc_info.value.code == "write_rejected"
    assert inner.calls == []


def test_readonly_commander_forwards_show_commands():
    inner = RecordingCommander()
    wrapped = ReadOnlyCommander(inner)
    wrapped.run_commands(["enable", "show hostname"])
    assert inner.calls == [["enable", "show hostname"]]
    assert inner.expect_disconnect_flags == [False]
