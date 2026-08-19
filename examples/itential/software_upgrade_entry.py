#!/usr/bin/env python
# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Itential workflow entrypoint for the refactored Software Upgrade - EOS action.

Expected JSON params (decorator / workflow input):

```json
{
  "device": "Arista",
  "version": "4.26.2F",
  "image": "vEOS64-lab-4.26.2F.swi",
  "flashMemory": "flash:",
  "confirm_reload": true
}
```

Use ``dry_run`` or ``skip_reload`` when the change window has not been
approved. ``confirm_reload`` must be true to execute ``reload force``.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Sequence, Union

from cloudvision.cvlib.actions import software_upgrade

Command = Union[str, Dict[str, Any]]


class UnsupportedCommander:
    """Placeholder commander for documentation / local dry-runs.

    Replace ``run_commands`` with a Gateway, eAPI, or CloudVision transport in
    a real deployment. Keeping this separate is what avoids vendor lock-in in
    the action core.
    """

    def run_commands(
        self,
        commands: Sequence[Command],
        *,
        expect_disconnect: bool = False,
    ) -> List[Dict[str, Any]]:
        raise RuntimeError(
            "No device transport configured. Provide a DeviceCommander "
            "implementation for your execution environment."
        )


def main(params: Dict[str, Any]) -> Dict[str, Any]:
    """Itential ``runCode`` / service entrypoint."""
    return software_upgrade(UnsupportedCommander(), params)


if __name__ == "__main__":
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    result = main(json.loads(raw or "{}"))
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if result.get("ok") else 1)
