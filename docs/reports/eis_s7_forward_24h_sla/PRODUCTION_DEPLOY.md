# PRODUCTION_DEPLOY

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

| Field | Value |
|---|---|
| HOST | S7 |
| SERVICE | tendermonitor-eis-parser.service |
| SOURCE | /opt/tendermonitor |
| BACKUP | `/opt/tendermonitor/bak-eis-s7-rgk-batch-20260817T162647` |
| S7_FORWARD_ONLY | YES |
| S13_BACKWARD_CHANGED | NO |
| S13_BACKWARD_SERVICE_CHANGE | NO (unit left `inactive`, not restarted) |
| QWEN_STARTED | NO |
| DOCUMENT_WORKERS_STARTED | NO |
| CRM_UI_CHANGED | NO |
| SERVICE_ACTIVE | YES |
| MAIN_PID | 3717828 |
| ACTIVE_ENTER | 2026-08-17 16:43:23 MSK |
| DB_AUTH | OK (connect check 55 regions) |
| UNION_ERRORS | 0 |
| CANONICAL_RUNTIME_HASH_MATCH | YES (sha256 of deployed files vs local working tree) |
| RUNTIME_COMMIT | `3d6a8f81b1b8d9778650681613ba2e9c39976262` |

Deployed files: `okpd_parser.py`, `rgk_record.py`, `rgk_batch.py`, `rgk_dirty.py`, `rgk_batch_sql.py`, `rgk_plan.py`, `rgk_batch_store.py`, `contract_registry_updater.py`, `contract_awarded_promoter.py`.

Live after deploy:

- Batch path is on: `RGK batch: input=500 duplicates=500 … elapsed=11.0s`
- First install corrupted trailing `r` via PowerShell `sed "s/\r$//"` (became `s/r$//`). Restored from backup and re-copied without sed.
- First persist of a non-empty remainder batch crashed on `links_documentation_44_fz_contract_id_fkey` (awarded id). Old per-row path swallowed that IntegrityError. Fixed in `3d6a8f8`: links only for main-table ids, insert before promote, savepoint on FK.

Catch-up note: region 20 RGK zip was already processed by the serial path; current batches are filename-dedup skips (~11s / 500 names on large `file_names_xml`).
