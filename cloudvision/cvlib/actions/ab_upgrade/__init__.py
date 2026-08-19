# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Read-only EOS A/B upgrade pair readiness (MVP1)."""

from .pair_readiness import pair_readiness, validate_pair_readiness_params
from .readonly import ReadOnlyCommander, validate_readonly_commands

__all__ = [
    "ReadOnlyCommander",
    "pair_readiness",
    "validate_pair_readiness_params",
    "validate_readonly_commands",
]
