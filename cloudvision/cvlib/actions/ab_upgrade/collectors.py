# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""Per-device read-only collectors for EOS A/B upgrade MVP1."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from cloudvision.cvlib.actions.ab_upgrade.inventory import (
    InventoryLookup,
    apply_inventory,
)
from cloudvision.cvlib.actions.ab_upgrade.models import DeviceSnapshot, Interfaces
from cloudvision.cvlib.actions.ab_upgrade.parsers import (
    last_show_payload,
    parse_bgp,
    parse_connectivity,
    parse_identity,
    parse_interfaces,
    parse_mlag,
    parse_mlag_sanity,
    parse_software,
)
from cloudvision.cvlib.actions.ab_upgrade.readonly import ReadOnlyCommander
from cloudvision.cvlib.actions.safe import WorkflowActionError

SHOW_HOSTNAME = "show hostname"
SHOW_VERSION = "show version"
SHOW_MLAG = "show mlag"
SHOW_MLAG_SANITY = "show mlag config-sanity"
SHOW_BGP_SUMMARY = "show ip bgp summary"
SHOW_INTERFACES = "show interfaces status"

COLLECT_COMMANDS = (
    SHOW_HOSTNAME,
    SHOW_VERSION,
    SHOW_MLAG,
    SHOW_MLAG_SANITY,
    SHOW_BGP_SUMMARY,
    SHOW_INTERFACES,
)


def _show(commander: ReadOnlyCommander, command: str) -> tuple:
    responses = commander.run_commands(["enable", command])
    return last_show_payload(["enable", command], responses)


def collect_device_snapshot(
    commander: ReadOnlyCommander,
    *,
    role: str,
    queried_as: str,
    inventory: Optional[InventoryLookup] = None,
) -> DeviceSnapshot:
    """Collect a read-only snapshot from one device.

    Transport failures become ``reachable=False`` on the snapshot. They do not
    raise, so the pair evaluator can still return ``ok: true`` with blockers.
    Write-rejection errors propagate so they fail the action.
    """
    hostname_payload: Any = None
    version_payload: Any = None
    mlag_payload: Any = None
    sanity_payload: Any = None
    bgp_payload: Any = None
    intf_payload: Any = None
    mlag_err: Optional[str] = None
    sanity_err: Optional[str] = None
    bgp_err: Optional[str] = None
    intf_err: Optional[str] = None
    errors: List[str] = []
    reachable = True
    cli_ok = True

    try:
        _, hostname_payload, err = _show(commander, SHOW_HOSTNAME)
        if err:
            errors.append(f"{SHOW_HOSTNAME}: {err}")
            cli_ok = False
        _, version_payload, err = _show(commander, SHOW_VERSION)
        if err:
            errors.append(f"{SHOW_VERSION}: {err}")
            cli_ok = False
        _, mlag_payload, mlag_err = _show(commander, SHOW_MLAG)
        _, sanity_payload, sanity_err = _show(commander, SHOW_MLAG_SANITY)
        _, bgp_payload, bgp_err = _show(commander, SHOW_BGP_SUMMARY)
        _, intf_payload, intf_err = _show(commander, SHOW_INTERFACES)
        if intf_err:
            errors.append(f"{SHOW_INTERFACES}: {intf_err}")
            cli_ok = False
    except WorkflowActionError:
        raise
    except Exception as exc:  # noqa: BLE001 - device may be unreachable
        reachable = False
        cli_ok = False
        errors.append(type(exc).__name__)

    software, extras = parse_software(version_payload)
    identity = parse_identity(role, queried_as, hostname_payload, extras)
    if not version_payload and not hostname_payload:
        reachable = False
        cli_ok = False

    mlag = parse_mlag(mlag_payload, mlag_err)
    sanity, issues = parse_mlag_sanity(sanity_payload, sanity_err)
    if sanity:
        mlag.config_sanity = mlag.config_sanity or sanity
    if issues:
        mlag.sanity_issues = issues
        if mlag.config_sanity is None:
            mlag.config_sanity = "inconsistent"

    bgp = parse_bgp(bgp_payload, bgp_err)
    interfaces = parse_interfaces(intf_payload) if intf_payload else Interfaces()

    snapshot = DeviceSnapshot(
        identity=identity,
        connectivity=parse_connectivity(
            reachable=reachable,
            cli_ok=cli_ok and reachable,
            uptime_seconds=extras.get("uptime_seconds"),
            error="; ".join(errors) if errors else None,
        ),
        software=software,
        mlag=mlag,
        bgp=bgp,
        interfaces=interfaces,
    )
    if inventory is not None:
        record = inventory.lookup(hostname=identity.hostname, serial=identity.serial)
        apply_inventory(snapshot, record)
    return snapshot


def collect_commands() -> Sequence[str]:
    """Return the exact show commands MVP1 will send after ``enable``."""
    return COLLECT_COMMANDS
