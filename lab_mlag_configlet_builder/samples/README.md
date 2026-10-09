# Sample inputs and expected EOS configlets

| File | Description |
| --- | --- |
| `lab01_inputs.yaml` | Shared MLAG domain, peer-link, VLAN 4094, peer IPs, and downstream LACP for LAB01A / LAB01B |
| `expected/LAB01A.cfg` | Expected generated configlet for LAB01A |
| `expected/LAB01B.cfg` | Expected generated configlet for LAB01B |

Regenerate expected files (should match git contents after intentional input changes):

```bash
python3 -m lab_mlag_configlet_builder \
  --inputs lab_mlag_configlet_builder/samples/lab01_inputs.yaml \
  --all \
  --output-dir lab_mlag_configlet_builder/samples/expected
```
