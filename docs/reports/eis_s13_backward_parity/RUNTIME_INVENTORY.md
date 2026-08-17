# RUNTIME_INVENTORY

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
Fresh clone HEAD `1156ba6e25b69d739e8791a2344b2a573511f5fa`. Inspected live S13 read-only. Did not restart S7 forward, PostgreSQL, CRM, Qwen, or document workers.

| Field | Value |
|---|---|
| BACKWARD_SERVICE_ACTIVE | YES (`active`) |
| BACKWARD_PID | 2445032 |
| BACKWARD_SOURCE_DATE | 2026-08-11 |
| BACKWARD_REGION_PROGRESS | `2026-08-11`: 3 regions; leftover key `2026-07-22`: 25 regions (636 bytes) |
| BACKWARD_CURRENT_DAY_STARTED_AT | 2026-08-17 22:00:53 MSK (unit ActiveEnterTimestamp after credential-rotation restart) |
| BACKWARD_RUNTIME_GIT_OR_HASH_STATE | live tree git `4f415376ad4e103ba01181f05c21390f0c3ec92c` branch `production-nyx-2026-02-09` (not this WIP) |
| BACKWARD_DB_HOST_ALIAS | S7 |
| BACKWARD_DB_NAME | `tender_monitor` |
| S13_TO_S7_DB_CONNECTION | PASS |
| Unit | `tendermonitor-eis-parser-backward.service` |
| Working directory | `/opt/tendermonitor` |
| User | `tendermonitor` |
| Interpreter | `/opt/tendermonitor/venv/bin/python` |
| Config | `/opt/tendermonitor/backward/config.ini` via `TENDERMONITOR_CONFIG` |
| Direction | `TENDERMONITOR_DIRECTION=backward` |
| Stop | `TENDERMONITOR_STOP_BEFORE=2021-01-01` |
| Requires | `eis-s7-gateway-forward.service` |
| S7 backward unit | `inactive` / `disabled` — do not enable |

PROVEN_RGK_BATCH_STACK_PRESENT_ON_S13_BEFORE=NO (live `/opt/tendermonitor` missing all six `rgk_*.py` modules).

Journal at inspect time showed serial per-contract UPDATEs about every 30–60s on 2026-08-11. Cursor was not moved.
