# IAG Run Code: CloudVision inventory lookup (static token)

Paste [`cvp_inventory_lookup.py`](cvp_inventory_lookup.py) into an IAG **Run Code** task. It only calls `cvprac` `get_inventory()` and looks up `USILD001LAB01A`. It does not send EOS configure, boot, or reload commands.

Store the CloudVision service-account token as IAG secret `cvp-token`. The script uses `$GATEWAYSECRET(cvp-token)`; do not paste the token into the task.

Install `cvprac` on the Gateway (`pip install cvprac`). This repository does not depend on it.

## Why this is not the HTTP adapter config

The existing Itential CVP adapter is a generic HTTPS client: you set protocol `https`, port `443`, base path `/cvpservice`, and `static_token`. That adapter prefixes every request with `/cvpservice`.

`cvprac.CvpClient.connect()` is not that adapter. Do **not** pass `/cvpservice` as a node, path, or `connect()` argument.

| Setting | Itential HTTP adapter | cvprac 2.2.0 on-prem (`is_cvaas=False`) |
| --- | --- | --- |
| Auth | `static_token` | `api_token=...` → `Authorization: Bearer ...` |
| Login | none (token on every call) | no `/login/authenticate.do`; health check `GET /api/v1/rest/` |
| Inventory | `/cvpservice/...` | `GET https://192.168.224.18:443/web/inventory/devices` |
| TLS | adapter verify flag | `cert=False` skip verify; `cert=True` or a CA path to verify |
| CVaaS only | n/a | `is_cvaas=True` prefixes `/cvpservice` instead of `/web` |

`192.168.224.18` is on-prem, so leave `is_cvaas=False` (the default). Username and password are required by the `connect()` signature but ignored when `api_token` is set; pass empty strings.

Token auth requires CloudVision 2020.3.0 or later. After connect, `get_inventory()` first calls `get_cvp_info()` (`/web/cvpInfo/getCvpInfo.do`) and then:

- API v1 (2018.1 and older): `/web/inventory/getInventory.do`
- API v2 (2018.2+, including current 2024/2025/2026): `/web/inventory/devices?provisioned=True`

You do not pick that path yourself. On typical on-prem nginx, `/web` and `/cvpservice` often reach the same backend; cvprac still uses `/web` unless you set `is_cvaas=True`.
