# PRODUCTION_DEPLOY

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

| Field | Value |
|---|---|
| HOST | S7 |
| SERVICE | tendermonitor-eis-parser.service |
| SOURCE | /opt/tendermonitor |
| S13_BACKWARD_CHANGED | NO |
| S13_BACKWARD_SERVICE_CHANGE | NO |
| QWEN_STARTED | NO |
| DOCUMENT_WORKERS_STARTED | NO |
| CRM_UI_CHANGED | NO |

Deploy procedure (executed after local tests PASS):

1. Snapshot live source-date / region_progress / unit PID
2. Backup only the files this WIP replaces under `/opt/tendermonitor/bak-eis-s7-rgk-batch-<timestamp>`
3. Install S7 forward files listed below as `tendermonitor:tendermonitor`
4. sha256 canonical vs runtime
5. Restart **only** `tendermonitor-eis-parser.service`

Files:

- `parsing_xml/okpd_parser.py`
- `parsing_xml/rgk_record.py` (new)
- `parsing_xml/rgk_batch.py` (new)
- `database_work/rgk_dirty.py` (new)
- `database_work/rgk_batch_sql.py` (new)
- `database_work/rgk_plan.py` (new)
- `database_work/rgk_batch_store.py` (new)
- `database_work/contract_registry_updater.py`
- `database_work/contract_awarded_promoter.py`

Live result: filled at deploy time.
