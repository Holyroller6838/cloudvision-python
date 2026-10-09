# Lab MLAG Configlet Builder (LAB01A / LAB01B)

Standalone Python tool that generates **device-specific Arista EOS MLAG configlets** for two existing lab switches: **LAB01A** and **LAB01B**.

This package is intentionally isolated from the enterprise CloudVision Python library and does **not** modify any existing CloudVision builders, APIs, or Studio examples.

## What it generates

For each device, the builder emits additive EOS configuration only:

- Shared MLAG domain (`domain-id`)
- Dedicated MLAG peer-link Port-Channel and member interfaces
- Peer VLAN (default **4094**) with trunk group + SVI addressing
- `mlag configuration` block (`local-interface`, `peer-address`, `peer-link`)
- Downstream LACP Port-Channel with an MLAG ID

## Safety constraints

The builder will **refuse** to emit configuration that:

- Resets interfaces (`default interface …`)
- Removes existing configuration with destructive `no` / `default` forms
- Touches management connectivity (`Management*`, `ma1`, VRF management addressing)

Output is plain EOS CLI suitable for CloudVision Static Configlets or paste into a lab switch.

## Quick start

```bash
# From repository root
python3 -m lab_mlag_configlet_builder.cli \
  --inputs lab_mlag_configlet_builder/samples/lab01_inputs.yaml \
  --device LAB01A

# Generate both devices into a directory
python3 -m lab_mlag_configlet_builder.cli \
  --inputs lab_mlag_configlet_builder/samples/lab01_inputs.yaml \
  --all \
  --output-dir /tmp/lab01-mlag-configlets
```

## Sample inputs

See [`samples/lab01_inputs.yaml`](samples/lab01_inputs.yaml). Configurable fields include:

| Field | Purpose |
| --- | --- |
| `domain_id` | Shared MLAG domain ID |
| `peer_vlan` | Peer VLAN (default 4094) |
| `peer_link.port_channel` / `members` | Dedicated peer-link interfaces |
| `devices.<name>.peer_svi_ip` | Local VLAN SVI address |
| `devices.<name>.peer_address` | Remote MLAG peer IP |
| `downstream.port_channel` / `members` / `mlag_id` | Downstream LACP + MLAG ID |

Expected configs for the sample inputs live in [`samples/expected/`](samples/expected/).

## Offline validation

```bash
python3 -m pytest lab_mlag_configlet_builder/tests -q
```

Tests cover:

1. Exact match against expected LAB01A / LAB01B configlets
2. Rejection of unsafe / management-impacting generation paths
3. Validation that output contains only additive EOS MLAG statements
