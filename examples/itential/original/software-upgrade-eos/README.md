# Software Upgrade - EOS (Itential baseline)

Source:
https://gitlab.com/itentialopensource/pre-built-automations/arista-eos-iag/-/blob/master/documentation/Software%20Upgrade%20-%20EOS.md

Kept here as the baseline reviewed for Itential workflow readiness.
Command text is extracted from the published mop/config templates; the
original IAP JSON bundles are not copied.

## Inputs

| Name | Example |
|------|---------|
| device | `Arista` |
| version | `4.26.2F` |
| image | `vEOS64-lab-4.26.2F.swi` |
| flashMemory | `flash:` |
| suppressSuccessMessage | `true` |
| suppressFailureMessage | `true` |

Outputs: none (`{}`).

## Flow

1. **File Verification** (`EOS - File Verification`)
   - `show ver` must **not** contain the target `version`
   - `dir <flashMemory>/<image>` must contain `Directory of ...` and must not
     contain `Error listing directory`
   - `show running-config | inc boot` must contain `boot system <flashMemory>`
2. **Pre Checks** (`EOS - Software Upgrade Checks`)
3. **Set Boot Config** (`EOS - Set Boot Config`)
4. **Reload** (`EOS - Reload` → `reload force`)
5. **Verify After Reload** (`EOS - Show Version`, 20 reattempts)
6. **Post Checks** (same mop as pre-checks)
7. **Pre Post Compare** (MOP diff, skipped when success messages are suppressed)
