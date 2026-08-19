# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Vendor-neutral device command protocol used by workflow actions."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Union

Command = Union[str, Dict[str, Any]]


class DeviceCommander(Protocol):
    """Vendor-neutral interface for running commands on a device."""

    def run_commands(
        self,
        commands: Sequence[Command],
        *,
        expect_disconnect: bool = False,
    ) -> List[Dict[str, Any]]:
        """Execute *commands* and return a list of response dicts.

        ``expect_disconnect`` is set when a command (for example ``reload``)
        is expected to drop the session. Callers must still treat a returned
        error as informational rather than always fatal.
        """


def first_command_error(responses: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """Return the first device error string, if any."""
    for response in responses:
        error = response.get("error") or response.get("errorMessage")
        if error:
            return str(error)
    return None


def command_text(response: Mapping[str, Any]) -> str:
    """Extract CLI output text from a device-command response dict."""
    for key in ("output", "response", "stdout"):
        value = response.get(key)
        if isinstance(value, str):
            return value
    result = response.get("result")
    if isinstance(result, str):
        return result
    if isinstance(result, Mapping):
        for key in ("output", "response", "stdout"):
            value = result.get(key)
            if isinstance(value, str):
                return value
    return ""


def joined_command_text(responses: Sequence[Mapping[str, Any]]) -> str:
    """Join all command outputs into a single string for rule matching."""
    return "\n".join(command_text(response) for response in responses)


class EosCtxCommander:
    """Adapter that runs commands via a CloudVision ``ctx`` object."""

    def __init__(self, ctx: Any):
        self._ctx = ctx

    def run_commands(
        self,
        commands: Sequence[Command],
        *,
        expect_disconnect: bool = False,
    ) -> List[Dict[str, Any]]:
        result = self._ctx.runDeviceCmds(
            list(commands),
            validateResponse=not expect_disconnect,
        )
        if expect_disconnect and not isinstance(result, list):
            return [{"result": "disconnect-expected"}]
        return list(result)
