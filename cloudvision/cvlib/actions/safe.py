# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Workflow-safe helpers for Python Actions invoked from orchestrators.

These helpers keep action results JSON-serializable, keep credentials out of
logs, and produce failures that are clear when surfaced in a workflow UI.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Mapping, Optional


# Keys that typically hold credentials or other secrets.
_SENSITIVE_KEY_RE = re.compile(
    r"(pass(word)?|token|secret|credential|authorization|auth|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)
_REDACTED = "***REDACTED***"


class WorkflowActionError(Exception):
    """Raised for expected action failures with a clear, serializable payload.

    Workflow platforms often only show ``str(exception)`` or a JSON result.
    This exception always carries a stable ``code`` and human-readable
    ``message`` so Job Viewer / workflow failure panes stay actionable.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "action_failed",
        details: Optional[Mapping[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": ensure_json_serializable(self.details),
            },
        }

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def ensure_json_serializable(value: Any) -> Any:
    """Return a JSON-serializable copy of *value*, or raise WorkflowActionError.

    Orchestrators (including Itential) require action outputs to round-trip
    through JSON. Non-serializable types (datetime, custom objects, bytes)
    commonly break the workflow hand-off after an otherwise successful run.
    """
    try:
        return json.loads(json.dumps(value, default=_json_default_reject))
    except (TypeError, ValueError) as exc:
        raise WorkflowActionError(
            f"Action result is not JSON-serializable: {exc}",
            code="serialization_error",
            details={"type": type(value).__name__},
        ) from None


def _json_default_reject(obj: Any) -> Any:
    raise TypeError(f"{type(obj).__name__} is not JSON serializable")


def redact_secrets(value: Any) -> Any:
    """Recursively redact credential-like fields for safe logging."""
    if isinstance(value, Mapping):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SENSITIVE_KEY_RE.search(key):
                redacted[key] = _REDACTED
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    return value


def workflow_result(
    *,
    ok: bool,
    data: Optional[Mapping[str, Any]] = None,
    error: Optional[WorkflowActionError] = None,
) -> Dict[str, Any]:
    """Build a consistent, JSON-serializable action result envelope."""
    if ok:
        payload: Dict[str, Any] = {"ok": True}
        if data:
            payload["data"] = dict(data)
        return ensure_json_serializable(payload)
    if error is None:
        error = WorkflowActionError("Action failed with no reason specified")
    return ensure_json_serializable(error.to_dict())
