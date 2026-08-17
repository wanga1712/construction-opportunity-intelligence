# PRODUCTION_VALIDATION

Host: S7 `/opt/tendermonitor`
Unit: `tendermonitor-eis-parser.service` only
Backup dir: `/opt/tendermonitor/bak-eis-recovery-20260817T152200`
Previous auth-file backup: `/opt/tendermonitor/database_work/db_credintials.env.bak-20260817T150457`

| Field | Value |
|---|---|
| CANONICAL_RUNTIME_HASH_MATCH | YES (sha256 of 9 deployed files) |
| SERVICE_RESTARTED | YES at 2026-08-17 15:21:36 MSK |
| SERVICE_ACTIVE_AFTER_RESTART | active |
| MAIN_PID | 3692779 |
| PROGRESS_AFTER_RESTART | YES — 44-FZ awarded recouped UPDATEs; metrics `source_date_start` for 2026-08-12 |
| AUTH_FAIL_AFTER_RESTART | 0 |
| UNION_SYNTAX_NEW_PID | 0 (one leftover line from old PID 3672485 at restart) |
| QWEN_STARTED | NO |
| DOCUMENT_WORKERS_STARTED | NO |
| CRM_UI_CHANGED | NO |

Correctness tests run locally: `eis_ingestion/tests` 12 passed, including 223-FZ mapping pin and UNION SQL parentheses.

Full BEFORE/AFTER object-count corpus on a completed source-date: NOT_MEASURED (day not complete).
