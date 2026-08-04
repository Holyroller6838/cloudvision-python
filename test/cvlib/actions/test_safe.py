# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

import json
from datetime import datetime

import pytest

from cloudvision.cvlib.actions.safe import (
    WorkflowActionError,
    ensure_json_serializable,
    redact_secrets,
    workflow_result,
)


def test_ensure_json_serializable_round_trip():
    payload = {"ok": True, "items": [1, "a", None], "nested": {"x": 1.5}}
    assert ensure_json_serializable(payload) == payload
    json.dumps(ensure_json_serializable(payload))


def test_ensure_json_serializable_rejects_datetime():
    with pytest.raises(WorkflowActionError) as exc_info:
        ensure_json_serializable({"when": datetime(2026, 1, 1)})
    assert exc_info.value.code == "serialization_error"


def test_redact_secrets_masks_credential_keys():
    raw = {
        "filename": "token.txt",
        "token": "super-secret",
        "nested": {"password": "p@ss", "hostname": "leaf1"},
        "headers": [{"Authorization": "Bearer abc"}],
    }
    redacted = redact_secrets(raw)
    assert redacted["filename"] == "token.txt"
    assert redacted["token"] == "***REDACTED***"
    assert redacted["nested"]["password"] == "***REDACTED***"
    assert redacted["nested"]["hostname"] == "leaf1"
    assert redacted["headers"][0]["Authorization"] == "***REDACTED***"
    assert "super-secret" not in json.dumps(redacted)


def test_workflow_result_success_and_failure_are_serializable():
    ok = workflow_result(ok=True, data={"filename": "a.txt"})
    assert ok == {"ok": True, "data": {"filename": "a.txt"}}
    json.dumps(ok)

    err = workflow_result(
        ok=False,
        error=WorkflowActionError("boom", code="device_command_failed", details={"n": 1}),
    )
    assert err["ok"] is False
    assert err["error"]["code"] == "device_command_failed"
    assert err["error"]["message"] == "boom"
    json.dumps(err)


def test_workflow_action_error_str_includes_code():
    err = WorkflowActionError("missing filename", code="invalid_input")
    assert str(err) == "[invalid_input] missing filename"
