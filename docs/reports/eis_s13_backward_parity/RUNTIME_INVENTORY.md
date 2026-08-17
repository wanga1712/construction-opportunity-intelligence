# RUNTIME_INVENTORY

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
Inspected live S13. Did not restart S7 forward, PostgreSQL, CRM, Qwen, or document workers.

| Field | Value |
|---|---|
| S13_BACKWARD_SERVICE_ACTIVE | YES |
| S13_BACKWARD_PID | 1304055 |
| S13_BACKWARD_SOURCE_DATE | 2026-08-11 |
| S13_BACKWARD_REGION_PROGRESS | 3 regions on `2026-08-11` in `/opt/tendermonitor/backward/region_progress.json` |
| S13_BACKWARD_RUNTIME_SOURCE | `/opt/tendermonitor/main.py` as user `tendermonitor` |
| S13_BACKWARD_CONFIG | `/opt/tendermonitor/backward/config.ini` via `TENDERMONITOR_CONFIG` |
| Unit | `/etc/systemd/system/tendermonitor-eis-parser-backward.service` |
| Nice / CPUWeight / MemoryMax | 15 / 50 / 4G |
| Requires | `eis-s7-gateway-forward.service` (EIS via S7 gateway) |
| `runtime.direction` | backward |
| config `stop_before_date` | 2026-04-01 |
| systemd `TENDERMONITOR_STOP_BEFORE` | 2021-01-01 (env; which wins is code-dependent) |
| RGK batch modules on `/opt/tendermonitor` | **absent** (`rgk_batch.py` / `rgk_plan.py` not present) |

`docs/PROJECT_OPERATING_RULES.md` still lists `tendermonitor-eis-parser-backward.service` on **S7**. Live unit is on **S13**. Do not start a second backward daemon on S7.
