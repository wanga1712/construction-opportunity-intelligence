# ROOT_CAUSE

## CASE A — production DB auth stall (fixed)

From 2026-08-17 12:05:19 until 15:05 the forward parser did no useful work.

Cause: operator password rotation updated `/opt/tendermonitor/.env` (`TENDERMONITOR_DB_PASSWORD`) but the parser reads `/opt/tendermonitor/database_work/db_credintials.env` (`DB_PASSWORD_TENDER`). Those files diverged. PostgreSQL itself did not restart.

Minimal fix (no role/ownership change): copy the rotated password into `DB_PASSWORD_TENDER` / `DB_PASSWORD_CATALOG` in `db_credintials.env`, mode 0640, owner `tendermonitor`. Backup: `db_credintials.env.bak-20260817T150457`. Restarted only `tendermonitor-eis-parser.service`.

`DB_AUTH_FAILURE_FIXED=YES`

Secrets are not recorded here.

## CASE B — 2026-08-12 still incomplete after auth recovery

`PERFORMANCE_OPTIMIZATION_REQUIRED=YES`

After reconnect, the parser resumed recouped/RGK 44-FZ sync for source-date 2026-08-12. Region checkpoint remained 4/55 because the current region had not finished.

## Invalid UNION ALL SQL (fixed in this WIP)

S7 `find_in_fz_one_query` emitted `... LIMIT 1 UNION ALL ...`. PostgreSQL rejects that. Live log: `syntax error at or near "UNION"`. Locator then returned None and the pipeline fell through to insert/unresolved paths.

Fix: parenthesize each `LIMIT 1` branch. After deploy, the only remaining UNION error was PID 3672485 at 15:21:36 (old process at restart). New PID 3692779: 0 UNION syntax errors.
