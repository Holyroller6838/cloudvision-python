# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Public MVP1 entrypoint: collect two device snapshots and evaluate pair readiness."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from cloudvision.cvlib.actions.ab_upgrade.collectors import collect_device_snapshot
from cloudvision.cvlib.actions.ab_upgrade.inventory import InventoryLookup
from cloudvision.cvlib.actions.ab_upgrade.models import BgpPolicy, ReadinessPolicy
from cloudvision.cvlib.actions.ab_upgrade.readiness import evaluate_pair_readiness
from cloudvision.cvlib.actions.ab_upgrade.readonly import ReadOnlyCommander
from cloudvision.cvlib.actions.commander import DeviceCommander
from cloudvision.cvlib.actions.safe import WorkflowActionError, workflow_result


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
        details={"field": field_name},
    )


def _as_string_list(value: Any, field_name: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
        return [item.strip() for item in value]
    raise WorkflowActionError(
        f"'{field_name}' must be a list of strings",
        code="invalid_input",
        details={"field": field_name},
    )


def _required_device(params: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise WorkflowActionError(
        f"Provide one of: {', '.join(repr(k) for k in keys)}",
        code="invalid_input",
        details={"field": keys[0]},
    )


def _critical_interfaces(params: Mapping[str, Any]) -> Dict[str, List[str]]:
    value = params.get("critical_interfaces")
    if value is None:
        return {}
    if isinstance(value, list):
        names = _as_string_list(value, "critical_interfaces")
        return {"A": list(names), "B": list(names)}
    if isinstance(value, Mapping):
        result: Dict[str, List[str]] = {}
        for role in ("A", "B", "a", "b"):
            if role in value:
                result[role.upper()] = _as_string_list(
                    value[role], f"critical_interfaces.{role}"
                )
        return result
    raise WorkflowActionError(
        "'critical_interfaces' must be a list or an object with A/B lists",
        code="invalid_input",
        details={"field": "critical_interfaces"},
    )


def validate_pair_readiness_params(params: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(params, Mapping):
        raise WorkflowActionError(
            "Action params must be a mapping/object",
            code="invalid_input",
        )
    device_a = _required_device(params, "device_a", "deviceA", "hostname_a")
    device_b = _required_device(params, "device_b", "deviceB", "hostname_b")
    bgp_params = params.get("bgp") if isinstance(params.get("bgp"), Mapping) else {}
    policy = ReadinessPolicy(
        expect_mlag=_as_bool(params.get("expect_mlag"), "expect_mlag", True),
        critical_interfaces=_critical_interfaces(params),
        bgp=BgpPolicy(
            required_vrfs=_as_string_list(bgp_params.get("required_vrfs"), "bgp.required_vrfs"),
            required_neighbors=_as_string_list(
                bgp_params.get("required_neighbors"), "bgp.required_neighbors"
            ),
            required_peer_groups=_as_string_list(
                bgp_params.get("required_peer_groups"), "bgp.required_peer_groups"
            ),
            ignored_neighbors=_as_string_list(
                bgp_params.get("ignored_neighbors"), "bgp.ignored_neighbors"
            ),
            require_all_established=_as_bool(
                bgp_params.get("require_all_established"),
                "bgp.require_all_established",
                False,
            ),
        ),
    )
    return {"device_a": device_a, "device_b": device_b, "policy": policy}


def pair_readiness(
    commander_a: DeviceCommander,
    commander_b: DeviceCommander,
    params: Mapping[str, Any],
    *,
    inventory: Optional[InventoryLookup] = None,
    collected_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Collect A/B snapshots and return an Itential-safe JSON envelope.

    Semantics:
    - ok true, pair.ready true  = collection succeeded and pair is ready
    - ok true, pair.ready false = collection succeeded, checks blocked readiness
    - ok false                  = input, transport-guard, or unexpected action failure
    """
    try:
        validated = validate_pair_readiness_params(params)
        policy: ReadinessPolicy = validated["policy"]
        snapshot_a = collect_device_snapshot(
            ReadOnlyCommander(commander_a),
            role="A",
            queried_as=validated["device_a"],
            inventory=inventory,
        )
        snapshot_b = collect_device_snapshot(
            ReadOnlyCommander(commander_b),
            role="B",
            queried_as=validated["device_b"],
            inventory=inventory,
        )
        ready, checks, blockers = evaluate_pair_readiness(snapshot_a, snapshot_b, policy)
        timestamp = collected_at or datetime.now(timezone.utc).isoformat()
        return workflow_result(
            ok=True,
            data={
                "mvp": "1",
                "mode": "read_only",
                "collected_at": timestamp,
                "devices": {
                    "A": snapshot_a.to_dict(),
                    "B": snapshot_b.to_dict(),
                },
                "pair": {
                    "ready": ready,
                    "checks": [item.to_dict() for item in checks],
                },
                "blocking_reasons": [item.to_dict() for item in blockers],
            },
        )
    except WorkflowActionError as exc:
        return workflow_result(ok=False, error=exc)
    except Exception as exc:  # noqa: BLE001 - keep workflow envelope JSON-safe
        unexpected = WorkflowActionError(
            "Unexpected error while collecting pair readiness",
            code="unexpected_error",
            details={"exception_type": type(exc).__name__},
        )
        return workflow_result(ok=False, error=unexpected)
