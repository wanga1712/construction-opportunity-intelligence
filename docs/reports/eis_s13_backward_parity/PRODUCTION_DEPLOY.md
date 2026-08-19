# PRODUCTION_DEPLOY.md

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## Phase 7: Live Cursor Before Deploy

| Metric | Value |
|---|---|
| BACKWARD_PID_BEFORE | 2445032 |
| BACKWARD_SOURCE_DATE_BEFORE | 2026-08-11 |
| BACKWARD_REGION_PROGRESS_BEFORE | 9/55 (regions: 1,2,10,15,16,18,20,21,23) |
| S7_FORWARD_SOURCE_DATE_BEFORE | 2026-07-29 |
| S7_FORWARD_REGION_PROGRESS_BEFORE | 50/55 |
| S7_FORWARD_PID_BEFORE | 3827083 |

## Phase 8: S7 DB Baseline (serial backward active)

| Metric | Baseline |
|---|---|
| S7_LOAD_BASELINE | 0.31 (1m) / 0.31 (5m) / 0.44 (15m) |
| S7_RAM_BASELINE | 2.7Gi used / 7.7Gi total |
| S7_DISK_IO_BASELINE | disk 74% full (60G free / 232G) |
| POSTGRES_ACTIVE_CONNECTIONS_BASELINE | 1 |
| POSTGRES_TOTAL_CONNECTIONS_BASELINE | 12 |
| POSTGRES_TX_RATE_BASELINE | 153208523 cumulative |
| POSTGRES_LOCKS_BASELINE | 33 |

## Phase 9: Backup

| Metric | Value |
|---|---|
| BACKWARD_RUNTIME_BACKUP_CREATED | YES |
| BACKWARD_RUNTIME_BACKUP_ALIAS | eis_s13_backward_pre_batch_deploy_20260819_124412 |
| BACKUP_PATH | /opt/tendermonitor/backups/eis_s13_backward_pre_batch_deploy_20260819_124412.tgz |

Files backed up: `parsing_xml/okpd_parser.py`, `database_work/contract_registry_locator.py`, `database_work/database_id_fetcher.py`, `database_work/database_operations.py`, `database_work/recouped_contract_sync.py`

## Phase 10: Deploy

Deployed 12 Git artifacts to `/opt/tendermonitor/` as `tendermonitor` user:

| File | Hash Match |
|---|---|
| parsing_xml/rgk_record.py | YES |
| parsing_xml/rgk_batch.py | YES |
| parsing_xml/okpd_parser.py | YES |
| database_work/contract_registry_locator.py | YES |
| database_work/database_id_fetcher.py | YES |
| database_work/database_operations.py | YES |
| database_work/recouped_contract_sync.py | YES |
| database_work/rgk_batch_sql.py | YES |
| database_work/rgk_batch_store.py | YES |
| database_work/rgk_dirty.py | YES |
| database_work/rgk_plan.py | YES |
| utils/source_day_metrics.py | YES |

**CANONICAL_RUNTIME_HASH_MATCH=YES**

Not modified: S7 forward code, S7 PostgreSQL config, CRM, Qwen, document workers, `db_credintials.env`.

## Phase 11: Restart Backward Only

| Metric | Value |
|---|---|
| BACKWARD_SERVICE_ACTIVE | YES |
| BACKWARD_PID_AFTER | 3959254 |
| BACKWARD_SOURCE_DATE_AFTER | 2026-08-11 |
| BACKWARD_REGION_PROGRESS_AFTER | 9/55 (resumed from checkpoint) |
| BACKWARD_CURSOR_PRESERVED | YES |

Log on restart: `"Найдено уже обработанных регионов для даты 2026-08-11: 9"` — confirmed checkpoint preserved.

Not restarted: `tendermonitor-eis-parser.service` (S7 forward), PostgreSQL, CRM Streamlit, Qwen, document workers.

## Phase 12: Immediate Canary

First RGK batch (region 26, 2026-08-11):

| Metric | Value |
|---|---|
| IMPORT_ERRORS | 0 |
| DB_ERRORS | 0 |
| FK_ERRORS | 0 |
| BATCH_ERRORS | 0 |
| UNHANDLED_EXCEPTIONS | 0 |
| LIVE_BATCH_XML | 3134 (full region 26 folder) |
| LIVE_BATCH_ELAPSED_SECONDS | 11.5 |
| LIVE_BATCH_INSERTED | 17 |
| LIVE_BATCH_UPDATED | 23 |
| LIVE_BATCH_UNCHANGED | 4 |
| LIVE_BATCH_UNRESOLVED | 172 |

Log shows aggregate/batch behavior: `RGK batch:` and `RGK folder:` summary lines instead of per-contract chatter.

Pre-existing known errors (not new, same as before deploy): `contractCutted` 223FZ files with no contract number in expected location — handled gracefully, no crash.

**S13_PRODUCTION_DEPLOYED=YES**
