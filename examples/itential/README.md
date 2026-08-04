# Itential-ready Python Actions

This directory documents how CloudVision Python Actions should be structured
when they are invoked from an Itential workflow (`runService` / `runCode`).

## Baseline reviewed

**Release:** [cloudvision-python-actions 2026.1.0](https://github.com/aristanetworks/cloudvision-python-actions/releases/tag/2026.1.0)  
**Asset:** `push-token-action-pack_1.2.1.tar`  
**Original files:** [`original/push-token/`](original/push-token/)

## Review: stock `push-token` action

```python
token = ctx.action.args.get("token")
filename = ctx.action.args.get("filename")
cmds = [
    "enable",
    {"cmd": f"copy terminal: file:{filename}", "input": token},
]
cmdResponses = ctx.runDeviceCmds(cmds)
errs = [resp.get("error") for resp in cmdResponses if resp.get("error")]
if errs:
    raise ActionFailed(f"Copying of token to {filename} failed with: {errs[0]}")
```

The pack’s `config.yaml` also declares `token` as a required plaintext
`dynamic-param` (not a secret), so the credential is part of the action /
workflow input surface by design.

Issues when that script is used from an Itential workflow:

| Risk | What goes wrong |
|------|-----------------|
| JSON serialization | No return value. Downstream workflow tasks have nothing JSON-safe to consume. |
| Credentials in logs | `token` is a required dynamic arg and sits inside `cmds`. Logging args/commands leaks the secret into Job Viewer. |
| Unclear failures | Missing/invalid `token`/`filename` surfaces as `TypeError`/`AttributeError`, not a clear validation error. |
| Vendor-specific | Hard dependency on CloudVision `ctx` and EOS `copy terminal: file:`. |

## Refactored implementation

Use `cloudvision.cvlib.actions.push_token`:

- `validate_push_token_params` / `resolve_secret` – clear input errors; prefer `token_env` so Itential injects the secret at runtime.
- `build_eos_push_commands` / `DeviceCommander` – EOS CLI is one backend behind a protocol.
- `commands_for_logging` / `redact_secrets` – never log the raw token.
- `push_token` – returns `{"ok": true, "data": ...}` or `{"ok": false, "error": {...}}`, always JSON-serializable.

### Itential entry example

```python
from cloudvision.cvlib.actions import push_token

class GatewayCommander:
    """Example commander that calls whatever transport Gateway provides."""

    def run_commands(self, commands):
        return device_api.run(commands)  # return list[dict]

def main(params: dict) -> dict:
    # params example: {"filename": "/tmp/cv-onboarding-token", "token_env": "CVP_TOKEN"}
    return push_token(GatewayCommander(), params)
```

Prefer decorating `token_env` as an Itential secret (`x-itential-secret-type: env`)
so the plaintext token never appears in workflow inputs or execution logs.
