# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Read-only DeviceCommander wrapper for EOS A/B upgrade MVP1.

MVP1 may send only privilege/read operations (``enable`` and ``show ...``).
Configuration, boot, reload, copy, write, and interactive-input commands are
rejected before they reach the underlying transport.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from cloudvision.cvlib.actions.commander import Command, DeviceCommander
from cloudvision.cvlib.actions.safe import WorkflowActionError

_ENABLE = re.compile(r"^enable$", re.IGNORECASE)
_SHOW = re.compile(r"^show(\s+|$)", re.IGNORECASE)
_WRITE_PREFIX = re.compile(
    r"^(configure|conf|config|boot|reload|write|copy|delete|del|erase|"
    r"install|bash|python|load|replace|rollback|clear|release|request|"
    r"watch|scp|sftp|wget|curl|no|set)\b",
    re.IGNORECASE,
)


def command_string(command: Command) -> str:
    """Return the CLI text of a DeviceCommander command object."""
    if isinstance(command, dict):
        return str(command.get("cmd") or command.get("command") or "").strip()
    return str(command).strip()


def validate_readonly_commands(commands: Sequence[Command]) -> None:
    """Raise WorkflowActionError if *commands* are not MVP1-safe."""
    if not commands:
        raise WorkflowActionError(
            "Read-only commander requires at least one command",
            code="invalid_input",
            details={"field": "commands"},
        )
    for command in commands:
        if isinstance(command, dict) and "input" in command:
            raise WorkflowActionError(
                "Interactive command input is not allowed in read-only MVP1",
                code="write_rejected",
                details={"command": command_string(command)},
            )
        text = command_string(command)
        if not text:
            raise WorkflowActionError(
                "Empty command is not allowed",
                code="write_rejected",
            )
        if _ENABLE.match(text) or _SHOW.match(text):
            continue
        raise WorkflowActionError(
            f"Command is not allowed in read-only MVP1: {text}",
            code="write_rejected",
            details={
                "command": text,
                "write_attempt": bool(_WRITE_PREFIX.match(text)),
            },
        )


class ReadOnlyCommander:
    """DeviceCommander adapter that refuses write and disconnect operations."""

    def __init__(self, inner: DeviceCommander):
        self._inner = inner

    def run_commands(
        self,
        commands: Sequence[Command],
        *,
        expect_disconnect: bool = False,
    ) -> List[Dict[str, Any]]:
        if expect_disconnect:
            raise WorkflowActionError(
                "expect_disconnect is not allowed in read-only MVP1",
                code="write_rejected",
                details={"expect_disconnect": True},
            )
        validate_readonly_commands(commands)
        return self._inner.run_commands(list(commands), expect_disconnect=False)
