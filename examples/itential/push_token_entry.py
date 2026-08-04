#!/usr/bin/env python
# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Itential workflow entrypoint for the refactored push-token action.

Expected JSON params (decorator / workflow input):

```json
{
  "filename": "cv-token.txt",
  "token_env": "CVP_DEVICE_TOKEN",
  "device_id": "optional-device-id"
}
```

``token_env`` should be wired to an Itential secret so the value is injected
as an environment variable at execution time and never stored in job inputs.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Sequence, Union

from cloudvision.cvlib.actions import push_token

Command = Union[str, Dict[str, Any]]


class UnsupportedCommander:
    """Placeholder commander for documentation / local dry-runs.

    Replace ``run_commands`` with a Gateway, NETCONF, or eAPI transport in a
    real deployment. Keeping this separate is what avoids vendor lock-in in
    the action core.
    """

    def run_commands(self, commands: Sequence[Command]) -> List[Dict[str, Any]]:
        raise RuntimeError(
            "No device transport configured. Provide a DeviceCommander "
            "implementation for your execution environment."
        )


def main(params: Dict[str, Any]) -> Dict[str, Any]:
    """Itential ``runCode`` / service entrypoint."""
    return push_token(UnsupportedCommander(), params)


if __name__ == "__main__":
    # Allow local invocation: python push_token_entry.py '{"filename":"x","token_env":"T"}'
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    result = main(json.loads(raw or "{}"))
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if result.get("ok") else 1)
