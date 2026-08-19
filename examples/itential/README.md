# Itential-ready Python Actions

This directory documents how CloudVision Python Actions should be structured
when they are invoked from an Itential workflow (`runService` / `runCode`).

## MVP1: read-only A/B pair readiness

Use [`ab_upgrade/`](ab_upgrade/) / `cloudvision.cvlib.actions.ab_upgrade.pair_readiness`.
It collects identity, connectivity, EOS version, MLAG, BGP, and interface
status from two devices and evaluates pair readiness in Python. It never
invokes `software_upgrade()` and never sends configure/boot/reload commands.

## Baseline reviewed

**Pre-built:** [Software Upgrade - EOS](https://gitlab.com/itentialopensource/pre-built-automations/arista-eos-iag/-/blob/master/documentation/Software%20Upgrade%20-%20EOS.md)  
**Project:** `itentialopensource/pre-built-automations/arista-eos-iag`  
**Original artifacts:** [`original/software-upgrade-eos/`](original/software-upgrade-eos/)

## Review: stock Itential workflow

The published workflow is a chain of IAG command/config templates:

1. File verification (`show ver`, `dir <flash>/<image>`, `show running-config | inc boot`)
2. Pre-checks (`EOS - Software Upgrade Checks`)
3. Set boot config (`boot system {{flashMemory}}{{image}}` + `write`)
4. Reload (`reload force`)
5. Verify after reload (`show version`, 20 reattempts)
6. Post-checks (same mop as pre-checks)
7. Optional pre/post MOP diff

Example inputs from the pre-built docs:

```json
{
  "suppressSuccessMessage": true,
  "suppressFailureMessage": true,
  "device": "Arista",
  "version": "4.26.2F",
  "image": "vEOS64-lab-4.26.2F.swi",
  "flashMemory": "flash:"
}
```

The workflow declares **no outputs** (`{}`).

Issues when that pattern is used from a Python Action / `runCode` task:

| Risk | What goes wrong |
|------|-----------------|
| JSON serialization | No structured result. Downstream workflow tasks have nothing JSON-safe to consume. |
| Destructive default | Always runs `reload force`. There is no dry-run or confirm flag. |
| Unclear failures | MOP pass/fail is opaque regex matching, not a stable error code. |
| Vendor-specific | Hard-wired to EOS CLI and IAG command templates. |
| Incomplete version check | Post-reload mop only looks for `Uptime`, not that the target image is active. |
| Not idempotent | If the device is already on the target version, file verification fails the job. |

`suppressSuccessMessage` / `suppressFailureMessage` only control IAP operator
prompts. They are accepted for input compatibility and do not change CLI
behavior.

## Refactored implementation

Use `cloudvision.cvlib.actions.software_upgrade`:

- `validate_software_upgrade_params` – clear input errors for `device`,
  `version`, `.swi` `image`, and `flashMemory` (`flash:`).
- `plan_software_upgrade` / EOS command builders – CLI is one backend behind
  a `DeviceCommander` protocol.
- `software_upgrade` – returns `{"ok": true, "data": ...}` or
  `{"ok": false, "error": {...}}`, always JSON-serializable.

Safety flags that the original workflow does not provide:

| Flag | Effect |
|------|--------|
| `dry_run` | Validate inputs and return the command plan. No device calls. |
| `skip_reload` | Set boot image and save, but do not reload. |
| `confirm_reload` | Required to execute `reload force`. |
| `already_upgraded_ok` | Treat "already on target version" as success. |

### Itential entry example

```python
from cloudvision.cvlib.actions import software_upgrade

class GatewayCommander:
    """Example commander that calls whatever transport Gateway provides."""

    def run_commands(self, commands, *, expect_disconnect=False):
        return device_api.run(commands)  # return list[dict]

def main(params: dict) -> dict:
    # Prefer dry_run or skip_reload until the change window is approved.
    return software_upgrade(GatewayCommander(), params)
```
