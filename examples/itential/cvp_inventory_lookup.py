#!/usr/bin/env python
# Copyright (c) 2026 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.

"""IAG Run Code: token login + get_inventory() lookup. Read-only."""

from cvprac.cvp_client import CvpClient

CVP_HOST = "192.168.224.18"
DEVICE_NAME = "USILD001LAB01A"


def _matches(device, name):
    hostname = str(device.get("hostname") or "")
    fqdn = str(device.get("fqdn") or "")
    return name in (
        hostname,
        fqdn,
        hostname.split(".")[0],
        fqdn.split(".")[0],
    )


def main(params=None):
    """IAG Run Code entry. Lookup target is fixed; ``params`` unused."""
    _ = params
    client = CvpClient()
    client.connect(
        nodes=[CVP_HOST],
        username="",
        password="",
        protocol="https",
        port=443,
        cert=False,
        api_token="$GATEWAYSECRET(cvp-token)",
    )
    inventory = client.api.get_inventory()
    device = next((item for item in inventory if _matches(item, DEVICE_NAME)), None)
    return {
        "ok": device is not None,
        "cvp": CVP_HOST,
        "hostname": DEVICE_NAME,
        "found": device is not None,
        "inventory_count": len(inventory),
        "device": device,
    }
