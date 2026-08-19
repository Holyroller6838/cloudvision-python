# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Optional read-only CloudVision inventory overlay for MVP1.

Unit tests inject a static lookup. Live DeviceService calls are never made
unless a caller provides an explicit lookup implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Protocol

from cloudvision.cvlib.actions.ab_upgrade.models import DeviceSnapshot


class InventoryLookup(Protocol):
    """Read-only device lookup. Must not mutate CloudVision or EOS."""

    def lookup(
        self,
        *,
        hostname: Optional[str] = None,
        serial: Optional[str] = None,
    ) -> Optional["InventoryRecord"]:
        """Return inventory facts for a hostname or serial, if known."""


@dataclass
class InventoryRecord:
    device_id: Optional[str] = None
    hostname: Optional[str] = None
    fqdn: Optional[str] = None
    model: Optional[str] = None
    software_version: Optional[str] = None
    streaming_status: Optional[str] = None
    system_mac: Optional[str] = None
    mlag_feature_enabled: Optional[bool] = None


_STREAMING_NAMES = {
    0: "UNSPECIFIED",
    1: "INACTIVE",
    2: "ACTIVE",
    "STREAMING_STATUS_UNSPECIFIED": "UNSPECIFIED",
    "STREAMING_STATUS_INACTIVE": "INACTIVE",
    "STREAMING_STATUS_ACTIVE": "ACTIVE",
}


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def inventory_record_from_cv_device(payload: Mapping[str, Any]) -> InventoryRecord:
    """Map a DeviceService JSON/dict (camelCase or snake_case) to InventoryRecord."""
    value = payload.get("value") if isinstance(payload.get("value"), Mapping) else payload
    if not isinstance(value, Mapping):
        return InventoryRecord()
    key = value.get("key") if isinstance(value.get("key"), Mapping) else {}
    streaming = value.get("streamingStatus") or value.get("streaming_status")
    if isinstance(streaming, int):
        streaming = _STREAMING_NAMES.get(streaming, str(streaming))
    elif isinstance(streaming, str):
        streaming = _STREAMING_NAMES.get(streaming, streaming.replace("STREAMING_STATUS_", ""))
    features = (
        _nested(value, "extendedAttributes", "featureEnabled")
        or _nested(value, "extended_attributes", "feature_enabled")
        or {}
    )
    mlag = None
    if isinstance(features, Mapping):
        for label in ("Mlag", "mlag", "MLAG"):
            if label in features:
                mlag = bool(features[label])
                break
    return InventoryRecord(
        device_id=_as_opt(
            (key or {}).get("deviceId") or (key or {}).get("device_id") or value.get("device_id")
        ),
        hostname=_as_opt(value.get("hostname")),
        fqdn=_as_opt(value.get("fqdn")),
        model=_as_opt(value.get("modelName") or value.get("model_name")),
        software_version=_as_opt(value.get("softwareVersion") or value.get("software_version")),
        streaming_status=_as_opt(streaming),
        system_mac=_as_opt(value.get("systemMacAddress") or value.get("system_mac_address")),
        mlag_feature_enabled=mlag,
    )


def _as_opt(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


class StaticInventory:
    """In-memory inventory for tests and offline wiring."""

    def __init__(self, records: Optional[List[InventoryRecord]] = None):
        self._records = list(records or [])

    def lookup(
        self,
        *,
        hostname: Optional[str] = None,
        serial: Optional[str] = None,
    ) -> Optional[InventoryRecord]:
        for record in self._records:
            if hostname and record.hostname == hostname:
                return record
            if serial and (record.device_id == serial or record.system_mac == serial):
                return record
        return None


def apply_inventory(snapshot: DeviceSnapshot, record: Optional[InventoryRecord]) -> DeviceSnapshot:
    """Fill snapshot gaps from inventory. Never overwrites non-empty CLI facts."""
    if record is None:
        return snapshot
    ident = snapshot.identity
    ident.cv_device_id = ident.cv_device_id or record.device_id
    ident.hostname = ident.hostname or record.hostname
    ident.fqdn = ident.fqdn or record.fqdn
    ident.model = ident.model or record.model
    ident.system_mac = ident.system_mac or record.system_mac
    ident.serial = ident.serial or record.device_id
    conn = snapshot.connectivity
    conn.streaming_status = conn.streaming_status or record.streaming_status
    software = snapshot.software
    if not software.eos_version and record.software_version:
        software.eos_version = record.software_version
        software.source = software.source or "cv_inventory"
    return snapshot
