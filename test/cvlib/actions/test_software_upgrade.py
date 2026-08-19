# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

import json
from typing import Any, Dict, List, Sequence

import pytest

from cloudvision.cvlib.actions.commander import command_text, first_command_error
from cloudvision.cvlib.actions.safe import WorkflowActionError
from cloudvision.cvlib.actions.software_upgrade import (
    DEFAULT_CHECK_COMMANDS,
    build_file_verification_commands,
    build_reload_commands,
    build_set_boot_commands,
    compare_check_outputs,
    is_already_on_version,
    parse_software_version,
    plan_software_upgrade,
    run_from_cv_context,
    software_upgrade,
    validate_software_upgrade_params,
    versions_match,
    wait_for_device_after_reload,
)
from cloudvision.cvlib.exceptions import ActionFailed

ITENTIAL_EXAMPLE = {
    "suppressSuccessMessage": True,
    "suppressFailureMessage": True,
    "device": "Arista",
    "version": "4.26.2F",
    "image": "vEOS64-lab-4.26.2F.swi",
    "flashMemory": "flash:",
}

SHOW_VERSION_OLD = """Arista vEOS
Software image version: 4.25.2F
Architecture:           x86_64
Uptime:                 2 days
"""

SHOW_VERSION_NEW = """Arista vEOS
Software image version: 4.26.2F
Architecture:           x86_64
Uptime:                 0 minutes
"""

DIR_OK = """Directory of flash:/vEOS64-lab-4.26.2F.swi

       -rwx   512000000           Jan 1  2024  vEOS64-lab-4.26.2F.swi
"""

BOOT_OK = "boot system flash:vEOS-4.25.2F.swi\n"


def _resp(output: str = "", error: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"result": {"output": output}}
    if error:
        payload["error"] = error
    return payload


class FakeCommander:
    def __init__(self, script=None, exc=None):
        self.script = script or []
        self.exc = exc
        self.calls: List[Sequence[Any]] = []
        self.expect_disconnect_flags: List[bool] = []
        self._index = 0

    def run_commands(self, commands, *, expect_disconnect=False):
        self.calls.append(list(commands))
        self.expect_disconnect_flags.append(expect_disconnect)
        if self.exc and not expect_disconnect:
            raise self.exc
        if self._index >= len(self.script):
            return [_resp("ok") for _ in commands]
        responses = self.script[self._index]
        self._index += 1
        return list(responses)


def _verification_script(version_output=SHOW_VERSION_OLD, dir_output=DIR_OK, boot_output=BOOT_OK):
    return [
        _resp(),  # enable
        _resp(version_output),
        _resp(dir_output),
        _resp(boot_output),
    ]


def _check_script(version_output=SHOW_VERSION_OLD, logging_output="Jan 1 00:00:00 syslog"):
    responses = [_resp()]  # enable
    for command in DEFAULT_CHECK_COMMANDS:
        if command == "show version":
            responses.append(_resp(version_output))
        elif command == "show logging":
            responses.append(_resp(logging_output))
        elif command == "show running-config":
            responses.append(_resp("hostname leaf1\n" + BOOT_OK))
        else:
            responses.append(_resp(f"{command} ok"))
    return responses


def _full_upgrade_script():
    return [
        _verification_script(),
        _check_script(SHOW_VERSION_OLD),
        [_resp() for _ in range(5)],  # set boot
        [_resp("Connection closed")],  # reload
        [
            _resp(),
            _resp(SHOW_VERSION_NEW),
        ],
        _check_script(SHOW_VERSION_NEW),
    ]


def test_validate_accepts_itential_example_inputs():
    params = validate_software_upgrade_params(ITENTIAL_EXAMPLE)
    assert params.device == "Arista"
    assert params.version == "4.26.2F"
    assert params.image == "vEOS64-lab-4.26.2F.swi"
    assert params.flash_memory == "flash:"
    assert params.boot_image == "flash:vEOS64-lab-4.26.2F.swi"
    assert params.image_dir_path == "flash:/vEOS64-lab-4.26.2F.swi"


def test_validate_accepts_boolean_strings():
    params = validate_software_upgrade_params(
        {**ITENTIAL_EXAMPLE, "dry_run": "true", "confirm_reload": "false"}
    )
    assert params.dry_run is True
    assert params.confirm_reload is False


def test_validate_rejects_bad_image_and_version():
    with pytest.raises(WorkflowActionError) as exc_info:
        validate_software_upgrade_params({**ITENTIAL_EXAMPLE, "image": "evil;rm.swi"})
    assert exc_info.value.details["field"] == "image"

    with pytest.raises(WorkflowActionError) as exc_info:
        validate_software_upgrade_params({**ITENTIAL_EXAMPLE, "version": "latest"})
    assert exc_info.value.details["field"] == "version"

    with pytest.raises(WorkflowActionError) as exc_info:
        validate_software_upgrade_params({**ITENTIAL_EXAMPLE, "flashMemory": "flash"})
    assert exc_info.value.details["field"] == "flashMemory"


def test_validate_requires_device():
    payload = dict(ITENTIAL_EXAMPLE)
    payload.pop("device")
    with pytest.raises(WorkflowActionError) as exc_info:
        validate_software_upgrade_params(payload)
    assert exc_info.value.code == "invalid_input"


def test_command_builders_match_itential_templates():
    params = validate_software_upgrade_params(ITENTIAL_EXAMPLE)
    assert build_file_verification_commands(params) == [
        "enable",
        "show version",
        "dir flash:/vEOS64-lab-4.26.2F.swi",
        "show running-config | include boot",
    ]
    assert build_set_boot_commands(params) == [
        "enable",
        "configure terminal",
        "boot system flash:vEOS64-lab-4.26.2F.swi",
        "end",
        "write memory",
    ]
    assert build_reload_commands() == ["enable", "reload force"]
    plan = plan_software_upgrade(params)
    assert "show logging" in plan["pre_checks"]
    assert "show boot" in plan["post_checks"]


def test_parse_software_version_and_match():
    assert parse_software_version(SHOW_VERSION_OLD) == "4.25.2F"
    assert parse_software_version("no version here") is None
    assert versions_match("4.26.2F", "4.26.2F")
    assert versions_match("4.26.2F-2GB", "4.26.2F")
    assert not versions_match("4.25.2F", "4.26.2F")
    assert is_already_on_version(SHOW_VERSION_NEW, "4.26.2F")
    assert not is_already_on_version(SHOW_VERSION_NEW, "4.26")
    assert is_already_on_version("version 4.26.2F present", "4.26.2F")


def test_command_text_and_first_error_helpers():
    assert command_text({"result": {"output": "hello"}}) == "hello"
    assert command_text({"output": "raw"}) == "raw"
    assert first_command_error([{"result": "ok"}, {"error": "% Invalid"}]) == "% Invalid"
    assert first_command_error([{"result": "ok"}]) is None


def test_dry_run_returns_plan_without_touching_device():
    commander = FakeCommander()
    result = software_upgrade(commander, {**ITENTIAL_EXAMPLE, "dry_run": True})
    assert result["ok"] is True
    assert result["data"]["dry_run"] is True
    assert result["data"]["reloaded"] is False
    assert result["data"]["plan"]["reload"] == ["enable", "reload force"]
    assert commander.calls == []
    json.dumps(result)


def test_reload_requires_explicit_confirmation():
    commander = FakeCommander(script=[_verification_script(), _check_script()])
    result = software_upgrade(commander, ITENTIAL_EXAMPLE)
    assert result["ok"] is False
    assert result["error"]["code"] == "reload_not_confirmed"
    # File verify + pre-checks ran; boot/reload did not.
    assert len(commander.calls) == 2
    assert not any(
        isinstance(cmd, str) and cmd.startswith("boot system")
        for call in commander.calls
        for cmd in call
    )


def test_skip_reload_sets_boot_without_reloading():
    commander = FakeCommander(script=[_verification_script(), _check_script(), [_resp()] * 5])
    result = software_upgrade(commander, {**ITENTIAL_EXAMPLE, "skip_reload": True})
    assert result["ok"] is True
    assert result["data"]["reloaded"] is False
    stage_names = [stage["name"] for stage in result["data"]["stages"]]
    assert stage_names == ["file_verification", "pre_checks", "set_boot_config", "reload"]
    assert result["data"]["stages"][-1]["skipped"] is True
    assert ["enable", "reload force"] not in commander.calls


def test_full_upgrade_success_is_json_serializable():
    commander = FakeCommander(script=_full_upgrade_script())
    sleeps: List[float] = []
    result = software_upgrade(
        commander,
        {**ITENTIAL_EXAMPLE, "confirm_reload": True},
        sleeper=sleeps.append,
    )
    assert result["ok"] is True
    assert result["data"]["reloaded"] is True
    assert result["data"]["current_version"] == "4.26.2F"
    stage_names = [stage["name"] for stage in result["data"]["stages"]]
    assert stage_names == [
        "file_verification",
        "pre_checks",
        "set_boot_config",
        "reload",
        "verify_after_reload",
        "post_checks",
        "pre_post_compare",
    ]
    assert commander.expect_disconnect_flags[3] is True
    json.dumps(result)


def test_already_upgraded_fails_by_default():
    commander = FakeCommander(script=[_verification_script(SHOW_VERSION_NEW)])
    result = software_upgrade(commander, ITENTIAL_EXAMPLE)
    assert result["ok"] is False
    assert result["error"]["code"] == "already_upgraded"


def test_already_upgraded_ok_is_idempotent_success():
    commander = FakeCommander(script=[_verification_script(SHOW_VERSION_NEW)])
    result = software_upgrade(
        commander,
        {**ITENTIAL_EXAMPLE, "already_upgraded_ok": True},
    )
    assert result["ok"] is True
    assert result["data"]["already_upgraded"] is True
    assert result["data"]["reloaded"] is False
    assert len(commander.calls) == 1


def test_missing_image_is_clear_error():
    commander = FakeCommander(
        script=[_verification_script(dir_output="% Error listing directory\n")]
    )
    result = software_upgrade(commander, ITENTIAL_EXAMPLE)
    assert result["ok"] is False
    assert result["error"]["code"] == "image_missing"


def test_missing_boot_system_is_clear_error():
    commander = FakeCommander(script=[_verification_script(boot_output="hostname leaf1\n")])
    result = software_upgrade(commander, ITENTIAL_EXAMPLE)
    assert result["ok"] is False
    assert result["error"]["code"] == "boot_config_missing"


def test_fatal_logs_fail_pre_checks():
    commander = FakeCommander(
        script=[
            _verification_script(),
            _check_script(logging_output="Fatal exception in driver"),
        ]
    )
    result = software_upgrade(commander, ITENTIAL_EXAMPLE)
    assert result["ok"] is False
    assert result["error"]["code"] == "fatal_logs_present"


def test_device_command_error_is_serialized():
    commander = FakeCommander(script=[[_resp(error="% Invalid input")]])
    result = software_upgrade(commander, ITENTIAL_EXAMPLE)
    assert result["ok"] is False
    assert result["error"]["code"] == "device_command_failed"
    assert "% Invalid input" in result["error"]["message"]
    json.dumps(result)


def test_unexpected_exception_is_wrapped():
    commander = FakeCommander(exc=RuntimeError("socket closed"))
    result = software_upgrade(commander, ITENTIAL_EXAMPLE)
    assert result["ok"] is False
    assert result["error"]["code"] == "unexpected_error"
    assert result["error"]["details"]["exception_type"] == "RuntimeError"
    assert "socket closed" not in result["error"]["message"]


def test_version_mismatch_after_reload():
    script = _full_upgrade_script()
    script[4] = [_resp(), _resp(SHOW_VERSION_OLD)]
    commander = FakeCommander(script=script)
    result = software_upgrade(
        commander,
        {**ITENTIAL_EXAMPLE, "confirm_reload": True},
        sleeper=lambda _: None,
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "version_mismatch"


def test_wait_for_device_retries_then_succeeds():
    commander = FakeCommander(
        script=[
            [_resp(error="timeout")],
            [_resp(), _resp("Software image version: 4.26.2F\nUptime: 1 minute\n")],
        ]
    )
    sleeps: List[float] = []
    responses = wait_for_device_after_reload(
        commander,
        retries=3,
        wait_seconds=5,
        sleeper=sleeps.append,
    )
    assert "Uptime" in responses[1]["result"]["output"]
    assert sleeps == [5]


def test_wait_for_device_times_out():
    commander = FakeCommander(script=[[_resp(error="timeout")] for _ in range(3)])
    with pytest.raises(WorkflowActionError) as exc_info:
        wait_for_device_after_reload(
            commander,
            retries=2,
            wait_seconds=1,
            sleeper=lambda _: None,
        )
    assert exc_info.value.code == "reload_timeout"


def test_compare_check_outputs():
    diff = compare_check_outputs(
        {"show version": "a", "show boot": "same"},
        {"show version": "b", "show boot": "same"},
    )
    by_cmd = {item["command"]: item["changed"] for item in diff}
    assert by_cmd["show version"] is True
    assert by_cmd["show boot"] is False


def test_custom_check_commands_keep_action_vendor_neutral():
    commander = FakeCommander(
        script=[
            _verification_script(),
            [_resp(), _resp("ok")],  # enable + custom pre-check
            [_resp()] * 5,
        ]
    )
    result = software_upgrade(
        commander,
        {
            **ITENTIAL_EXAMPLE,
            "skip_reload": True,
            "pre_check_commands": ["show hostname"],
        },
    )
    assert result["ok"] is True
    assert commander.calls[1] == ["enable", "show hostname"]


class _FakeCtx:
    def __init__(self, args, responses=None):
        self.action = type("A", (), {"args": args})()
        self._responses = responses or _verification_script(SHOW_VERSION_NEW)

    def getDevice(self):
        return type("D", (), {"id": "JPE123", "hostName": "leaf1"})()

    def runDeviceCmds(self, cmds, validateResponse=True):
        return self._responses


def test_run_from_cv_context_already_upgraded_ok():
    ctx = _FakeCtx({**ITENTIAL_EXAMPLE, "already_upgraded_ok": True})
    result = run_from_cv_context(ctx)
    assert result["ok"] is True
    assert result["data"]["device"] == "Arista"


def test_run_from_cv_context_raises_action_failed():
    ctx = _FakeCtx(ITENTIAL_EXAMPLE, responses=[_resp(error="nope")])
    with pytest.raises(ActionFailed) as exc_info:
        run_from_cv_context(ctx)
    assert "nope" in str(exc_info.value)


def test_validation_failure_does_not_call_device():
    commander = FakeCommander()
    result = software_upgrade(commander, {"device": "Arista"})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert commander.calls == []
