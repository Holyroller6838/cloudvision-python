#!/usr/bin/env python
# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Itential Run Code entrypoint for EOS A/B upgrade MVP1 (read-only).

Wire ``commander_a`` / ``commander_b`` to Gateway, eAPI, or CloudVision
``ctx.runDeviceCmds`` adapters. This module never calls software_upgrade().

Expected JSON params:

```json
{
  "device_a": "leaf-a",
  "device_b": "leaf-b",
  "expect_mlag": true,
  "bgp": {
    "required_peer_groups": ["SPINES"],
    "ignored_neighbors": ["192.0.2.254"]
  }
}
```
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Sequence, Union

from cloudvision.cvlib.actions.ab_upgrade import pair_readiness

Command = Union[str, Dict[str, Any]]


class UnsupportedCommander:
    """Placeholder until a Gateway/eAPI/CV DeviceCommander is injected."""

    def __init__(self, role: str):
        self.role = role

    def run_commands(
        self,
        commands: Sequence[Command],
        *,
        expect_disconnect: bool = False,
    ) -> List[Dict[str, Any]]:
        raise RuntimeError(
            f"No device transport configured for {self.role}. Provide a "
            "DeviceCommander implementation for your execution environment."
        )


def main(
    params: Dict[str, Any],
    commander_a=None,
    commander_b=None,
) -> Dict[str, Any]:
    """Itential ``runCode`` / service entrypoint."""
    return pair_readiness(
        commander_a or UnsupportedCommander("A"),
        commander_b or UnsupportedCommander("B"),
        params,
    )


if __name__ == "__main__":
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    result = main(json.loads(raw or "{}"))
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if result.get("ok") else 1)
