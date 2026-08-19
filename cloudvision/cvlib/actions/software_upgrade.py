# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Upgrade EOS on a device using the Itential Software Upgrade - EOS flow.

Baseline reviewed
-----------------
Itential pre-built: ``arista-eos-iag`` *Software Upgrade - EOS*
https://gitlab.com/itentialopensource/pre-built-automations/arista-eos-iag/-/blob/master/documentation/Software%20Upgrade%20-%20EOS.md

The published workflow is a chain of IAG command/config templates. Capabilities:

1. Verify the device is not already on the target version and that the image
   file is present on flash.
2. Run pre-check show commands.
3. Set ``boot system <flash><image>`` and save.
4. Reload the device.
5. Wait until the device is reachable after reload.
6. Run post-check show commands.
7. Optionally compare pre-check and post-check output.

When that workflow is dropped into a Python Action / ``runCode`` task several
issues appear:

1. **JSON serialization** – the workflow declares no outputs (``{}``).
   Downstream tasks have nothing structured to consume.
2. **Destructive default** – ``reload force`` always runs; there is no dry-run
   or explicit confirmation flag.
3. **Unclear failures** – MOP pass/fail is opaque regex matching without
   stable error codes.
4. **Vendor-specific** – logic is hard-wired to EOS CLI and IAG templates.
5. **Incomplete version check** – the post-reload mop only looks for
   ``Uptime``, not that the target image is active (despite the docs).
6. **Not idempotent** – if the device is already on the target version, file
   verification fails the whole job.

This module factors the behavior into small, testable functions with a
device-commander protocol so EOS is one backend, not the whole action.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from .commander import (
    Command,
    DeviceCommander,
    EosCtxCommander,
    command_text,
    first_command_error,
    joined_command_text,
)
from .safe import WorkflowActionError, ensure_json_serializable, redact_secrets, workflow_result

logger = logging.getLogger(__name__)

Sleeper = Callable[[float], None]

# Filenames stay in the device filesystem namespace the operator named.
_IMAGE_RE = re.compile(r"^[A-Za-z0-9._+-]+\.swi$")
_FLASH_RE = re.compile(r"^[A-Za-z0-9_-]+:$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+([._-][0-9A-Za-z]+)*$")
_SOFTWARE_VERSION_RE = re.compile(
    r"Software image version:\s*(\S+)",
    re.IGNORECASE,
)

# Itential mop ``EOS - Software Upgrade Checks`` (show commands only; the
# Architecture=x86_64 regex is lab-specific and is not applied by default).
DEFAULT_CHECK_COMMANDS: List[str] = [
    "show version",
    "show running-config",
    "show ip interface brief",
    "show license",
    "show clock",
    "show logging",
    "show platform bios",
    "show boot",
]

# Itential child job ``Verify After Reload`` used 20 reattempts. Wait is
# expressed in seconds here (the IAG field unit is ambiguous).
DEFAULT_RELOAD_RETRIES = 20
DEFAULT_RELOAD_WAIT_SECONDS = 60.0


@dataclass(frozen=True)
class SoftwareUpgradeParams:
    """Validated inputs for :func:`software_upgrade`."""

    device: str
    version: str
    image: str
    flash_memory: str
    confirm_reload: bool = False
    dry_run: bool = False
    skip_reload: bool = False
    already_upgraded_ok: bool = False
    compare_checks: bool = True
    reload_retries: int = DEFAULT_RELOAD_RETRIES
    reload_wait_seconds: float = DEFAULT_RELOAD_WAIT_SECONDS
    pre_check_commands: Sequence[str] = field(default_factory=lambda: list(DEFAULT_CHECK_COMMANDS))
    post_check_commands: Sequence[str] = field(default_factory=lambda: list(DEFAULT_CHECK_COMMANDS))

    @property
    def boot_image(self) -> str:
        """EOS ``boot system`` argument: ``flash:image.swi``."""
        return f"{self.flash_memory}{self.image}"

    @property
    def image_dir_path(self) -> str:
        """EOS ``dir`` argument used by the Itential file-verification mop."""
        flash = self.flash_memory.rstrip("/")
        if flash.endswith(":"):
            return f"{flash}/{self.image}"
        return f"{flash}/{self.image}"


def _as_bool(value: Any, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise WorkflowActionError(
        f"'{field_name}' must be a boolean",
        code="invalid_input",
        details={"field": field_name, "type": type(value).__name__},
    )


def _as_positive_number(value: Any, field_name: str, default: float, integer: bool = False):
    if value is None:
        return int(default) if integer else default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkflowActionError(
            f"'{field_name}' must be a number",
            code="invalid_input",
            details={"field": field_name},
        )
    if value < 0:
        raise WorkflowActionError(
            f"'{field_name}' must be >= 0",
            code="invalid_input",
            details={"field": field_name},
        )
    return int(value) if integer else float(value)


def _required_string(params: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = params.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str) or not value.strip():
            raise WorkflowActionError(
                f"'{key}' must be a non-empty string",
                code="invalid_input",
                details={"field": key},
            )
        return value.strip()
    raise WorkflowActionError(
        f"Provide one of: {', '.join(repr(k) for k in keys)}",
        code="invalid_input",
        details={"field": keys[0]},
    )


def _optional_command_list(params: Mapping[str, Any], field_name: str) -> Optional[List[str]]:
    value = params.get(field_name)
    if value is None:
        return None
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise WorkflowActionError(
            f"'{field_name}' must be a list of non-empty strings",
            code="invalid_input",
            details={"field": field_name},
        )
    return [item.strip() for item in value]


def validate_software_upgrade_params(params: Mapping[str, Any]) -> SoftwareUpgradeParams:
    """Validate workflow inputs and return a typed params object."""
    if not isinstance(params, Mapping):
        raise WorkflowActionError(
            "Action params must be a mapping/object",
            code="invalid_input",
        )

    device = _required_string(params, "device", "device_id", "deviceName")
    version = _required_string(params, "version")
    image = _required_string(params, "image")
    flash_memory = _required_string(params, "flashMemory", "flash_memory")

    if not _VERSION_RE.match(version):
        raise WorkflowActionError(
            "'version' is not a valid EOS version string",
            code="invalid_input",
            details={"field": "version"},
        )
    if not _IMAGE_RE.match(image):
        raise WorkflowActionError(
            "'image' must be a .swi filename with no path separators",
            code="invalid_input",
            details={"field": "image"},
        )
    if not _FLASH_RE.match(flash_memory):
        raise WorkflowActionError(
            "'flashMemory' must look like 'flash:' or 'drive:'",
            code="invalid_input",
            details={"field": "flashMemory"},
        )

    pre_checks = _optional_command_list(params, "pre_check_commands")
    post_checks = _optional_command_list(params, "post_check_commands")

    return SoftwareUpgradeParams(
        device=device,
        version=version,
        image=image,
        flash_memory=flash_memory,
        confirm_reload=_as_bool(params.get("confirm_reload"), "confirm_reload", False),
        dry_run=_as_bool(params.get("dry_run"), "dry_run", False),
        skip_reload=_as_bool(params.get("skip_reload"), "skip_reload", False),
        already_upgraded_ok=_as_bool(
            params.get("already_upgraded_ok"), "already_upgraded_ok", False
        ),
        compare_checks=_as_bool(params.get("compare_checks"), "compare_checks", True),
        reload_retries=_as_positive_number(
            params.get("reload_retries"), "reload_retries", DEFAULT_RELOAD_RETRIES, integer=True
        ),
        reload_wait_seconds=_as_positive_number(
            params.get("reload_wait_seconds"),
            "reload_wait_seconds",
            DEFAULT_RELOAD_WAIT_SECONDS,
        ),
        pre_check_commands=pre_checks if pre_checks is not None else list(DEFAULT_CHECK_COMMANDS),
        post_check_commands=(
            post_checks if post_checks is not None else list(DEFAULT_CHECK_COMMANDS)
        ),
    )


def build_file_verification_commands(params: SoftwareUpgradeParams) -> List[Command]:
    """Commands from Itential mop ``EOS - File Verification``."""
    return [
        "enable",
        "show version",
        f"dir {params.image_dir_path}",
        "show running-config | include boot",
    ]


def build_check_commands(commands: Sequence[str]) -> List[Command]:
    """Wrap operator show commands with ``enable``."""
    return ["enable", *commands]


def build_set_boot_commands(params: SoftwareUpgradeParams) -> List[Command]:
    """Commands from Itential template ``EOS - Set Boot Config``."""
    return [
        "enable",
        "configure terminal",
        f"boot system {params.boot_image}",
        "end",
        "write memory",
    ]


def build_reload_commands() -> List[Command]:
    """Commands from Itential mop ``EOS - Reload``."""
    return ["enable", "reload force"]


def build_show_version_commands() -> List[Command]:
    """Commands from Itential mop ``EOS - Show Version``."""
    return ["enable", "show version"]


def plan_software_upgrade(params: SoftwareUpgradeParams) -> Dict[str, List[Command]]:
    """Return the EOS command plan without executing anything."""
    return {
        "file_verification": build_file_verification_commands(params),
        "pre_checks": build_check_commands(params.pre_check_commands),
        "set_boot_config": build_set_boot_commands(params),
        "reload": build_reload_commands(),
        "verify_after_reload": build_show_version_commands(),
        "post_checks": build_check_commands(params.post_check_commands),
    }


def parse_software_version(output: str) -> Optional[str]:
    """Parse ``Software image version`` from EOS ``show version`` output."""
    match = _SOFTWARE_VERSION_RE.search(output)
    if not match:
        return None
    return match.group(1).rstrip(",")


def versions_match(current: Optional[str], target: str) -> bool:
    """Return True when *current* is the requested target version."""
    if current is None:
        return False
    current_base = current.split("-", 1)[0]
    target_base = target.split("-", 1)[0]
    return current == target or current_base == target_base


def is_already_on_version(output: str, target: str) -> bool:
    """Return True when ``show version`` output is already the target image.

    Prefer the parsed ``Software image version`` field so a short target like
    ``4.26`` does not match ``4.26.2F`` via substring. Fall back to a
    substring check only when the field cannot be parsed (Itential mop used
    ``contains`` / ``!contains`` on ``show ver``).
    """
    current = parse_software_version(output)
    if current is not None:
        return versions_match(current, target)
    return target in output


def _run(
    commander: DeviceCommander,
    commands: Sequence[Command],
    *,
    stage: str,
    expect_disconnect: bool = False,
) -> List[Dict[str, Any]]:
    logger.info("Running stage %s commands=%s", stage, redact_secrets(list(commands)))
    responses = commander.run_commands(commands, expect_disconnect=expect_disconnect)
    if expect_disconnect:
        return list(responses)
    error = first_command_error(responses)
    if error:
        raise WorkflowActionError(
            f"Stage '{stage}' failed: {error}",
            code="device_command_failed",
            details={"stage": stage},
        )
    return list(responses)


def _outputs_by_command(
    commands: Sequence[Command],
    responses: Sequence[Mapping[str, Any]],
) -> Dict[str, str]:
    outputs: Dict[str, str] = {}
    for command, response in zip(commands, responses):
        if command == "enable":
            continue
        name = command if isinstance(command, str) else str(command.get("cmd", command))
        outputs[name] = command_text(response)
    return outputs


def verify_image_present(output: str, params: SoftwareUpgradeParams) -> None:
    """Apply Itential file-verification rules for ``dir <flash>/<image>``."""
    if "Error listing directory" in output:
        raise WorkflowActionError(
            f"Image {params.image} was not found on {params.flash_memory}",
            code="image_missing",
            details={"path": params.image_dir_path},
        )
    expected = f"Directory of {params.image_dir_path}"
    if expected not in output and params.image not in output:
        raise WorkflowActionError(
            f"Image {params.image} was not found on {params.flash_memory}",
            code="image_missing",
            details={"path": params.image_dir_path},
        )


def verify_boot_uses_flash(output: str, params: SoftwareUpgradeParams) -> None:
    """Apply Itential rule that running-config contains ``boot system <flash>``."""
    needle = f"boot system {params.flash_memory}"
    if needle not in output:
        raise WorkflowActionError(
            f"Running-config does not contain '{needle}'",
            code="boot_config_missing",
            details={"expected": needle},
        )


def verify_no_fatal_logs(output: str) -> None:
    """Apply Itential pre/post rule that logging must not contain ``Fatal``."""
    if "Fatal" in output:
        raise WorkflowActionError(
            "Device logs contain 'Fatal' entries",
            code="fatal_logs_present",
        )


def compare_check_outputs(
    before: Mapping[str, str],
    after: Mapping[str, str],
) -> List[Dict[str, Any]]:
    """Return a JSON-safe list of pre/post differences (Itential MOP Diff)."""
    keys = sorted(set(before) | set(after))
    diff: List[Dict[str, Any]] = []
    for key in keys:
        left = before.get(key, "")
        right = after.get(key, "")
        if left != right:
            diff.append({"command": key, "changed": True})
        else:
            diff.append({"command": key, "changed": False})
    return diff


def wait_for_device_after_reload(
    commander: DeviceCommander,
    *,
    retries: int,
    wait_seconds: float,
    sleeper: Sleeper,
) -> List[Dict[str, Any]]:
    """Retry ``show version`` until ``Uptime`` is present (device is back)."""
    last_error = "device did not return show version"
    attempts = retries + 1
    for attempt in range(attempts):
        try:
            responses = commander.run_commands(
                build_show_version_commands(),
                expect_disconnect=False,
            )
            error = first_command_error(responses)
            if not error:
                output = joined_command_text(responses)
                if "Uptime" in output:
                    return list(responses)
                last_error = "device responded but 'Uptime' was missing from show version"
            else:
                last_error = error
        except Exception as exc:  # noqa: BLE001 - device may still be rebooting
            last_error = type(exc).__name__
        if attempt < retries:
            sleeper(wait_seconds)
    raise WorkflowActionError(
        f"Device did not come back after reload: {last_error}",
        code="reload_timeout",
        details={"retries": retries, "wait_seconds": wait_seconds},
    )


def _stage_result(name: str, **extra: Any) -> Dict[str, Any]:
    payload = {"name": name, "ok": True}
    payload.update(extra)
    return payload


def _file_verification_stage(
    commander: DeviceCommander,
    params: SoftwareUpgradeParams,
) -> Dict[str, Any]:
    commands = build_file_verification_commands(params)
    responses = _run(commander, commands, stage="file_verification")
    outputs = _outputs_by_command(commands, responses)
    version_output = outputs.get("show version", "")
    current_version = parse_software_version(version_output)
    already = is_already_on_version(version_output, params.version)
    if already:
        if params.already_upgraded_ok:
            return _stage_result(
                "file_verification",
                already_upgraded=True,
                current_version=current_version or params.version,
            )
        raise WorkflowActionError(
            f"Device is already running EOS {params.version}",
            code="already_upgraded",
            details={"current_version": current_version, "target_version": params.version},
        )
    verify_image_present(outputs.get(f"dir {params.image_dir_path}", ""), params)
    verify_boot_uses_flash(outputs.get("show running-config | include boot", ""), params)
    return _stage_result(
        "file_verification",
        already_upgraded=False,
        current_version=current_version,
    )


def _check_stage(
    commander: DeviceCommander,
    params: SoftwareUpgradeParams,
    *,
    stage: str,
    commands: Sequence[str],
) -> Dict[str, Any]:
    full = build_check_commands(commands)
    responses = _run(commander, full, stage=stage)
    outputs = _outputs_by_command(full, responses)
    logging_output = outputs.get("show logging", "")
    if logging_output:
        verify_no_fatal_logs(logging_output)
    return _stage_result(stage, outputs=outputs)


def software_upgrade(
    commander: DeviceCommander,
    params: Mapping[str, Any],
    *,
    sleeper: Optional[Sleeper] = None,
) -> Dict[str, Any]:
    """Run the Software Upgrade - EOS workflow and return a JSON result.

    This is the primary entrypoint for Itential ``runService`` / ``runCode``
    tasks and for unit tests.
    """
    try:
        validated = validate_software_upgrade_params(params)
        sleep = sleeper if sleeper is not None else time.sleep
        plan = plan_software_upgrade(validated)
        logger.info(
            "Software upgrade device=%s version=%s image=%s dry_run=%s skip_reload=%s",
            validated.device,
            validated.version,
            validated.image,
            validated.dry_run,
            validated.skip_reload,
        )

        if validated.dry_run:
            return workflow_result(
                ok=True,
                data={
                    "device": validated.device,
                    "target_version": validated.version,
                    "image": validated.image,
                    "flash_memory": validated.flash_memory,
                    "boot_image": validated.boot_image,
                    "dry_run": True,
                    "reloaded": False,
                    "plan": {name: list(cmds) for name, cmds in plan.items()},
                },
            )

        stages: List[Dict[str, Any]] = []
        file_stage = _file_verification_stage(commander, validated)
        stages.append(file_stage)
        if file_stage.get("already_upgraded"):
            return workflow_result(
                ok=True,
                data=_result_payload(
                    validated,
                    stages=stages,
                    reloaded=False,
                    already_upgraded=True,
                    current_version=file_stage.get("current_version"),
                ),
            )

        pre = _check_stage(
            commander,
            validated,
            stage="pre_checks",
            commands=validated.pre_check_commands,
        )
        stages.append(pre)

        reloaded = False
        current_version = file_stage.get("current_version")
        if not validated.skip_reload and not validated.confirm_reload:
            raise WorkflowActionError(
                "Set confirm_reload=true to reload the device, or set skip_reload/"
                "dry_run to avoid reload",
                code="reload_not_confirmed",
                details={"device": validated.device},
            )

        _run(commander, plan["set_boot_config"], stage="set_boot_config")
        stages.append(_stage_result("set_boot_config", boot_image=validated.boot_image))

        if validated.skip_reload:
            stages.append(_stage_result("reload", skipped=True))
        else:
            _run(
                commander,
                plan["reload"],
                stage="reload",
                expect_disconnect=True,
            )
            reloaded = True
            stages.append(_stage_result("reload", skipped=False))
            verify_responses = wait_for_device_after_reload(
                commander,
                retries=validated.reload_retries,
                wait_seconds=validated.reload_wait_seconds,
                sleeper=sleep,
            )
            version_output = joined_command_text(verify_responses)
            current_version = parse_software_version(version_output)
            on_target = (
                versions_match(current_version, validated.version)
                if current_version is not None
                else validated.version in version_output
            )
            if not on_target:
                raise WorkflowActionError(
                    "Device came back but is not running the target EOS version",
                    code="version_mismatch",
                    details={
                        "current_version": current_version,
                        "target_version": validated.version,
                    },
                )
            stages.append(
                _stage_result(
                    "verify_after_reload",
                    current_version=current_version or validated.version,
                )
            )

        post_outputs: Dict[str, str] = {}
        if not validated.skip_reload:
            post = _check_stage(
                commander,
                validated,
                stage="post_checks",
                commands=validated.post_check_commands,
            )
            stages.append(post)
            post_outputs = post.get("outputs") or {}
            if validated.compare_checks:
                stages.append(
                    _stage_result(
                        "pre_post_compare",
                        diff=compare_check_outputs(pre.get("outputs") or {}, post_outputs),
                    )
                )

        return workflow_result(
            ok=True,
            data=_result_payload(
                validated,
                stages=stages,
                reloaded=reloaded,
                already_upgraded=False,
                current_version=current_version,
            ),
        )
    except WorkflowActionError as exc:
        logger.error("software_upgrade failed: %s", exc)
        return workflow_result(ok=False, error=exc)
    except Exception as exc:  # noqa: BLE001 - convert unexpected errors for workflows
        unexpected = WorkflowActionError(
            "Unexpected error while upgrading EOS",
            code="unexpected_error",
            details={"exception_type": type(exc).__name__},
        )
        logger.exception("software_upgrade unexpected error: %s", unexpected)
        return workflow_result(ok=False, error=unexpected)


def _result_payload(
    params: SoftwareUpgradeParams,
    *,
    stages: Iterable[Mapping[str, Any]],
    reloaded: bool,
    already_upgraded: bool,
    current_version: Optional[str],
) -> Dict[str, Any]:
    return {
        "device": params.device,
        "target_version": params.version,
        "image": params.image,
        "flash_memory": params.flash_memory,
        "boot_image": params.boot_image,
        "dry_run": False,
        "reloaded": reloaded,
        "already_upgraded": already_upgraded,
        "current_version": current_version,
        "stages": [dict(stage) for stage in stages],
    }


def run_from_cv_context(ctx: Any) -> Dict[str, Any]:
    """CloudVision Action pack entry helper.

    Reads arguments from ``ctx.action.args`` but still returns a JSON result.
    """
    args = dict(getattr(getattr(ctx, "action", None), "args", None) or {})
    device = None
    get_device = getattr(ctx, "getDevice", None)
    if callable(get_device):
        device = get_device()
    if device is not None and "device" not in args and "device_id" not in args:
        args["device"] = getattr(device, "id", None) or getattr(device, "hostName", None)
    result = software_upgrade(EosCtxCommander(ctx), args)
    if not result.get("ok"):
        from cloudvision.cvlib import ActionFailed

        err = result.get("error") or {}
        raise ActionFailed(err.get("message") or "software_upgrade failed")
    ensure_json_serializable(result)
    return result
