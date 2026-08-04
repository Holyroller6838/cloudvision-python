# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

import json
import logging
from typing import Any, Dict, List, Sequence

import pytest

from cloudvision.cvlib.actions.push_token import (
    EosPushTokenCommander,
    build_eos_push_commands,
    commands_for_logging,
    first_command_error,
    push_token,
    resolve_secret,
    run_from_cv_context,
    validate_push_token_params,
)
from cloudvision.cvlib.actions.safe import WorkflowActionError
from cloudvision.cvlib.exceptions import ActionFailed


class FakeCommander:
    def __init__(self, responses=None, exc=None):
        self.responses = (
            responses if responses is not None else [{"result": "ok"}, {"result": "ok"}]
        )
        self.exc = exc
        self.calls: List[Sequence[Any]] = []

    def run_commands(self, commands: Sequence[Any]) -> List[Dict[str, Any]]:
        self.calls.append(commands)
        if self.exc:
            raise self.exc
        return list(self.responses)


def test_resolve_secret_prefers_environment_injection():
    secret = resolve_secret(
        {"token_env": "CVP_TOKEN", "token": "should-not-use"},
        environ={"CVP_TOKEN": "from-env"},
    )
    assert secret == "from-env"


def test_resolve_secret_falls_back_to_direct_value():
    assert resolve_secret({"token": "direct"}, environ={}) == "direct"


def test_resolve_secret_missing_raises_clear_error():
    with pytest.raises(WorkflowActionError) as exc_info:
        resolve_secret({}, environ={})
    assert exc_info.value.code == "missing_secret"


def test_resolve_secret_empty_env_raises_clear_error():
    with pytest.raises(WorkflowActionError) as exc_info:
        resolve_secret({"token_env": "MISSING"}, environ={})
    assert exc_info.value.code == "missing_secret"
    assert "MISSING" in exc_info.value.message


def test_validate_push_token_params_rejects_bad_filename():
    with pytest.raises(WorkflowActionError) as exc_info:
        validate_push_token_params({"filename": "evil;rm -rf", "token": "t"})
    assert exc_info.value.code == "invalid_input"
    assert exc_info.value.details["field"] == "filename"


def test_validate_push_token_params_requires_filename():
    with pytest.raises(WorkflowActionError) as exc_info:
        validate_push_token_params({"token": "t"})
    assert "filename" in exc_info.value.message


def test_build_eos_push_commands_shape():
    cmds = build_eos_push_commands("sekrit", "flash:token")
    assert cmds[0] == "enable"
    assert cmds[1] == {"cmd": "copy terminal: file:flash:token", "input": "sekrit"}


def test_commands_for_logging_redacts_input():
    cmds = build_eos_push_commands("sekrit", "flash:token")
    safe = commands_for_logging(cmds)
    assert safe[1]["input"] == "***REDACTED***"
    assert "sekrit" not in json.dumps(safe)


def test_first_command_error():
    responses = [
        {"result": "ok"},
        {"error": "% Invalid input"},
    ]
    assert first_command_error(responses) == "% Invalid input"
    assert first_command_error([{"result": "ok"}]) is None


def test_push_token_success_returns_json_serializable_result():
    commander = FakeCommander()
    result = push_token(
        commander,
        {"filename": "flash:token", "token_env": "T", "device_id": "JPE123"},
        environ={"T": "sekrit"},
    )
    assert result["ok"] is True
    assert result["data"]["filename"] == "flash:token"
    assert result["data"]["device_id"] == "JPE123"
    assert result["data"]["commands_run"] == 2
    json.dumps(result)
    assert commander.calls[0][1]["input"] == "sekrit"


def test_push_token_device_error_is_clear_and_serializable():
    commander = FakeCommander(responses=[{"error": "permission denied"}])
    result = push_token(
        commander,
        {"filename": "flash:token", "token": "sekrit"},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "device_command_failed"
    assert "permission denied" in result["error"]["message"]
    json.dumps(result)


def test_push_token_validation_failure_does_not_call_device():
    commander = FakeCommander()
    result = push_token(commander, {"token": "sekrit"})
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert commander.calls == []


def test_push_token_unexpected_exception_is_wrapped():
    commander = FakeCommander(exc=RuntimeError("socket closed"))
    result = push_token(
        commander,
        {"filename": "flash:token", "token": "sekrit"},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "unexpected_error"
    assert result["error"]["details"]["exception_type"] == "RuntimeError"
    # Do not leak the raw exception text by default (may contain sensitive data).
    assert "socket closed" not in result["error"]["message"]


def test_push_token_logs_do_not_contain_secret(caplog):
    commander = FakeCommander()
    with caplog.at_level(logging.INFO, logger="cloudvision.cvlib.actions.push_token"):
        push_token(
            commander,
            {"filename": "flash:token", "token": "super-secret-value"},
        )
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "super-secret-value" not in joined
    assert "***REDACTED***" in joined


def test_custom_command_builder_keeps_action_vendor_neutral():
    def nxos_builder(token, filename):
        return [{"cmd": f"copy running-config {filename}", "input": token}]

    commander = FakeCommander(responses=[{"result": "ok"}])
    result = push_token(
        commander,
        {"filename": "bootflash:token", "token": "sekrit"},
        command_builder=nxos_builder,
    )
    assert result["ok"] is True
    assert commander.calls[0][0]["cmd"] == "copy running-config bootflash:token"


class _FakeCtx:
    def __init__(self, args, responses=None, error=None):
        self.action = type("A", (), {"args": args})()
        self._responses = responses or [{"result": "ok"}, {"result": "ok"}]
        self._error = error
        self.logged = []

    def getDevice(self):
        return type("D", (), {"id": "dev-1"})()

    def runDeviceCmds(self, cmds):
        if self._error:
            return [{"error": self._error}]
        return self._responses

    def info(self, msg):
        self.logged.append(msg)


def test_eos_push_token_commander_delegates_to_ctx():
    ctx = _FakeCtx({"filename": "f", "token": "t"})
    commander = EosPushTokenCommander(ctx)
    assert commander.run_commands(["enable"]) == [{"result": "ok"}, {"result": "ok"}]


def test_run_from_cv_context_success():
    ctx = _FakeCtx({"filename": "flash:token", "token": "sekrit"})
    result = run_from_cv_context(ctx)
    assert result["ok"] is True
    assert result["data"]["device_id"] == "dev-1"


def test_run_from_cv_context_raises_action_failed():
    ctx = _FakeCtx({"filename": "flash:token", "token": "sekrit"}, error="nope")
    with pytest.raises(ActionFailed) as exc_info:
        run_from_cv_context(ctx)
    assert "nope" in str(exc_info.value)
