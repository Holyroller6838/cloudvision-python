# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Helpers and actions designed for workflow orchestration platforms."""

from .ab_upgrade import pair_readiness, validate_pair_readiness_params
from .commander import (
    DeviceCommander,
    EosCtxCommander,
    command_text,
    first_command_error,
)
from .safe import WorkflowActionError, ensure_json_serializable, redact_secrets, workflow_result
from .software_upgrade import (
    SoftwareUpgradeParams,
    build_file_verification_commands,
    build_reload_commands,
    build_set_boot_commands,
    parse_software_version,
    plan_software_upgrade,
    run_from_cv_context,
    software_upgrade,
    validate_software_upgrade_params,
)

__all__ = [
    "DeviceCommander",
    "EosCtxCommander",
    "SoftwareUpgradeParams",
    "WorkflowActionError",
    "build_file_verification_commands",
    "build_reload_commands",
    "build_set_boot_commands",
    "command_text",
    "ensure_json_serializable",
    "first_command_error",
    "pair_readiness",
    "parse_software_version",
    "plan_software_upgrade",
    "redact_secrets",
    "run_from_cv_context",
    "software_upgrade",
    "validate_pair_readiness_params",
    "validate_software_upgrade_params",
    "workflow_result",
]
