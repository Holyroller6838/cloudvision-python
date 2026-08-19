# EOS A/B upgrade MVP1 (read-only)

Itential entrypoint: [`pair_readiness_entry.py`](pair_readiness_entry.py)

This workflow **only reads**. It does not run `configure`, `boot system`,
`reload`, image transfer, GSHUT, or `software_upgrade()`.

## Run Code

```python
from examples.itential.ab_upgrade.pair_readiness_entry import main

# Inject DeviceCommander instances that call Gateway / eAPI / CV runDeviceCmds.
result = main(params, commander_a=gateway_a, commander_b=gateway_b)
```

`main()` returns the `pair_readiness()` JSON envelope:

- `ok: true`, `pair.ready: true` — collection succeeded, pair is ready
- `ok: true`, `pair.ready: false` — collection succeeded, operational blockers
- `ok: false` — input or action failure

## Params

```json
{
  "device_a": "leaf-a",
  "device_b": "leaf-b",
  "expect_mlag": true,
  "critical_interfaces": ["Port-Channel2000", "Vlan4094"],
  "bgp": {
    "required_vrfs": ["default"],
    "required_peer_groups": ["SPINES"],
    "ignored_neighbors": ["192.0.2.254"]
  }
}
```

If `critical_interfaces` is omitted and `expect_mlag` is true, MVP1 uses each
device's MLAG peer-link and local interface as the critical set.
