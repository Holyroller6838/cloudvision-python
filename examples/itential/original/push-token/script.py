# Copyright (c) 2022 Arista Networks, Inc.
# Use of this source code is governed by the Apache License 2.0
# that can be found in the COPYING file.
#
# Source: aristanetworks/cloudvision-python-actions
# Release: https://github.com/aristanetworks/cloudvision-python-actions/releases/tag/2026.1.0
# Asset: push-token-action-pack_1.2.1.tar
# Kept here as the baseline reviewed for Itential workflow readiness.

from typing import List, Dict
from cloudvision.cvlib import ActionFailed

token = ctx.action.args.get("token")
filename = ctx.action.args.get("filename")

cmds = [
    "enable",
    {"cmd": f"copy terminal: file:{filename}", "input": token},
]
cmdResponses: List[Dict] = ctx.runDeviceCmds(cmds)
# Iterate through the list of responses for the commands, and if an error occurred in
# any of the commands, raise an exception
# Only consider the first error that is encountered
# as following commands require previous ones to succeed
errs = [resp.get('error') for resp in cmdResponses if resp.get('error')]
if errs:
    raise ActionFailed(f"Copying of token to {filename} failed with: {errs[0]}")
