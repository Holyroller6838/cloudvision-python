# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Push a secret/token onto a device filesystem.

Original CloudVision ``push-token`` action (reviewed for Itential use)
--------------------------------------------------------------------
Baseline:
https://github.com/aristanetworks/cloudvision-python-actions/releases/tag/2026.1.0
(``push-token-action-pack_1.2.1.tar``).

The stock action is a top-level script that reads ``token`` / ``filename``
from ``ctx.action.args``, builds EOS CLI commands with the raw token, and
raises ``ActionFailed`` on device errors.  When that pattern is dropped
into an Itential (or similar) workflow, several issues appear:

1. **JSON serialization** – the script returns nothing. Workflows need a
   JSON-serializable success/failure payload to pass to the next task.
2. **Credentials in logs** – the token lives in action args and in the
   command list. Logging ``cmds`` or ``args`` (common while debugging)
   writes the secret into Job Viewer / execution logs.
3. **Unclear workflow failure** – missing ``token`` / ``filename`` become
   ``TypeError`` / ``AttributeError`` instead of a clear validation error.
4. **Vendor-specific** – logic is hard-wired to CloudVision ``ctx`` and
   EOS ``copy terminal: file:`` CLI, so the same action cannot target
   another controller or OS without a rewrite.

This module factors the behavior into small, testable functions with a
device-commander protocol so EOS is one backend, not the whole action.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Union

from .safe import WorkflowActionError, ensure_json_serializable, redact_secrets, workflow_result

logger = logging.getLogger(__name__)

Command = Union[str, Dict[str, Any]]

# Filenames must stay on the device filesystem namespace the operator named.
# Allow ``:`` for EOS URLs such as ``flash:token`` / ``certificate:x.crt``.
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._/: -]+$")


class DeviceCommander(Protocol):
    """Vendor-neutral interface for running commands on a device."""

    def run_commands(self, commands: Sequence[Command]) -> List[Dict[str, Any]]:
        """Execute *commands* and return a list of response dicts."""


@dataclass(frozen=True)
class PushTokenParams:
    """Validated inputs for :func:`push_token`."""

    token: str
    filename: str
    device_id: Optional[str] = None


def resolve_secret(
    params: Mapping[str, Any],
    *,
    value_key: str = "token",
    env_key: str = "token_env",
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve a secret from an env var name or (discouraged) direct value.

    Prefer Itential / Gateway secret injection: pass ``token_env`` as the
    *name* of an environment variable that already holds the secret. The
    plaintext value then never appears in workflow input forms or job args.
    """
    env = environ if environ is not None else os.environ
    env_name = params.get(env_key)
    if env_name:
        if not isinstance(env_name, str) or not env_name.strip():
            raise WorkflowActionError(
                f"'{env_key}' must be a non-empty environment variable name",
                code="invalid_input",
                details={"field": env_key},
            )
        secret = env.get(env_name)
        if not secret:
            raise WorkflowActionError(
                f"Environment variable '{env_name}' is not set or empty",
                code="missing_secret",
                details={"field": env_key, "env_name": env_name},
            )
        return secret

    direct = params.get(value_key)
    if direct is None or direct == "":
        raise WorkflowActionError(
            f"Provide '{env_key}' (preferred) or '{value_key}'",
            code="missing_secret",
            details={"field": value_key},
        )
    if not isinstance(direct, str):
        raise WorkflowActionError(
            f"'{value_key}' must be a string",
            code="invalid_input",
            details={"field": value_key, "type": type(direct).__name__},
        )
    return direct


def validate_push_token_params(
    params: Mapping[str, Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> PushTokenParams:
    """Validate workflow inputs and return a typed params object."""
    if not isinstance(params, Mapping):
        raise WorkflowActionError(
            "Action params must be a mapping/object",
            code="invalid_input",
        )

    filename = params.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise WorkflowActionError(
            "'filename' is required and must be a non-empty string",
            code="invalid_input",
            details={"field": "filename"},
        )
    filename = filename.strip()
    if not _SAFE_FILENAME_RE.match(filename):
        raise WorkflowActionError(
            "'filename' contains unsupported characters",
            code="invalid_input",
            details={"field": "filename"},
        )

    token = resolve_secret(params, environ=environ)
    device_id = params.get("device_id")
    if device_id is not None and not isinstance(device_id, str):
        raise WorkflowActionError(
            "'device_id' must be a string when provided",
            code="invalid_input",
            details={"field": "device_id"},
        )

    return PushTokenParams(token=token, filename=filename, device_id=device_id)


def build_eos_push_commands(token: str, filename: str) -> List[Command]:
    """Build EOS CLI commands that write *token* into *filename*.

    Isolated so other vendors can supply their own command builders without
    changing the orchestration / validation flow.
    """
    return [
        "enable",
        {"cmd": f"copy terminal: file:{filename}", "input": token},
    ]


def commands_for_logging(commands: Sequence[Command]) -> List[Command]:
    """Return a log-safe copy of *commands* with secret inputs redacted."""
    safe: List[Command] = []
    for command in commands:
        if isinstance(command, dict):
            # EOS interactive copy puts the secret in ``input``.
            redacted_cmd = dict(command)
            if "input" in redacted_cmd:
                redacted_cmd["input"] = "***REDACTED***"
            safe.append(redact_secrets(redacted_cmd))
        else:
            safe.append(command)
    return safe


def first_command_error(responses: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """Return the first device error string, if any."""
    for response in responses:
        error = response.get("error")
        if error:
            return str(error)
    return None


def push_token(
    commander: DeviceCommander,
    params: Mapping[str, Any],
    *,
    environ: Optional[Mapping[str, str]] = None,
    command_builder=build_eos_push_commands,
) -> Dict[str, Any]:
    """Push a token to a device and return a JSON-serializable result.

    This is the primary entrypoint for Itential ``runService`` / ``runCode``
    tasks and for unit tests. It never logs the raw token.
    """
    try:
        validated = validate_push_token_params(params, environ=environ)
        commands = command_builder(validated.token, validated.filename)
        logger.info(
            "Pushing token to %s (device_id=%s) with commands=%s",
            validated.filename,
            validated.device_id,
            commands_for_logging(commands),
        )
        responses = commander.run_commands(commands)
        error = first_command_error(responses)
        if error:
            raise WorkflowActionError(
                f"Copying token to {validated.filename} failed: {error}",
                code="device_command_failed",
                details={"filename": validated.filename, "device_id": validated.device_id},
            )
        return workflow_result(
            ok=True,
            data={
                "filename": validated.filename,
                "device_id": validated.device_id,
                "commands_run": len(commands),
            },
        )
    except WorkflowActionError as exc:
        logger.error("push_token failed: %s", exc)
        return workflow_result(ok=False, error=exc)
    except Exception as exc:  # noqa: BLE001 - convert unexpected errors for workflows
        unexpected = WorkflowActionError(
            "Unexpected error while pushing token",
            code="unexpected_error",
            details={"exception_type": type(exc).__name__},
        )
        logger.exception("push_token unexpected error: %s", unexpected)
        return workflow_result(ok=False, error=unexpected)


class EosPushTokenCommander:
    """Adapter that runs push-token commands via a CloudVision ``ctx`` object.

    Kept separate from :func:`push_token` so the core action stays free of the
    CloudVision runtime and can be unit-tested with a fake commander.
    """

    def __init__(self, ctx: Any):
        self._ctx = ctx

    def run_commands(self, commands: Sequence[Command]) -> List[Dict[str, Any]]:
        return list(self._ctx.runDeviceCmds(list(commands)))


def run_from_cv_context(ctx: Any) -> Dict[str, Any]:
    """CloudVision Action pack entry helper.

    Reads arguments from ``ctx.action.args`` but still returns a JSON result
    and avoids logging credentials.
    """
    args = dict(getattr(getattr(ctx, "action", None), "args", None) or {})
    device = None
    get_device = getattr(ctx, "getDevice", None)
    if callable(get_device):
        device = get_device()
    if device is not None and "device_id" not in args:
        args["device_id"] = getattr(device, "id", None)
    result = push_token(EosPushTokenCommander(ctx), args)
    # CV actions typically signal failure by raising; preserve that contract
    # while still producing a serializable result for workflow callers.
    if not result.get("ok"):
        from cloudvision.cvlib import ActionFailed

        err = result.get("error") or {}
        raise ActionFailed(err.get("message") or "push_token failed")
    ensure_json_serializable(result)
    return result
