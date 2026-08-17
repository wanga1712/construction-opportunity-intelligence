# PROJECT-EIS-END-TO-END-SOURCE-AND-24H-SLA-RECONCILIATION-1
# Factual inventory. No secrets. No unification of S7/S13.

## Contours (do not mix)

| Id | Host | Unit | Role | ExecStart |
|---|---|---|---|---|
| A | S7 | `tendermonitor-eis-parser.service` enabled/active | forward/current EIS ingestion | `/opt/tendermonitor/venv/bin/python /opt/tendermonitor/main.py` |
| B | S13 | `tendermonitor-eis-parser-backward.service` enabled/active | backward/historical EIS ingestion | same `main.py`, env `TENDERMONITOR_DIRECTION=backward` |
| C | S13 | `tender-docs-daemon-open/awarded` inactive/disabled | document processor | `/opt/tender_documents_research/.venv/bin/python -m document_processor.daemon` — already in Git under `tender_documents_research/document_processor/` |

S7 also has `tendermonitor-eis-parser-backward.service` **disabled/inactive**. S13 has no forward parser unit.

## S7 forward (A)

- User: `tendermonitor`
- WorkingDirectory: `/opt/tendermonitor`
- EnvironmentFile: none
- Env: `PATH=/opt/tendermonitor/venv/bin`
- Drop-in: `resource-boost.conf` (CPUWeight=400, IOWeight=400, Nice=-5)
- Interpreter: `/opt/tendermonitor/venv/bin/python`
- Config: `/opt/tendermonitor/config.ini` (no EnvironmentFile)
- DB env file (not imported): `database_work/db_credintials.env` keys `DB_*_TENDER`
- EIS HTTP: `http://localhost:8080/eis-integration/services/getDocsIP` via `eis-stunnel.service` (CryptoPro stunnel_thread)
- 44-FZ: subsystems PRIZ (new) + RGK (recouped); doctypes listed in config.ini.example
- 223-FZ: RI223 + RD223
- Cursor: `[eis] date` updated **before** a date is processed (`update_config_date`)
- Region checkpoint: `region_progress.json` via `mark_region_processed`
- Date completion: `eis_requester.process_requests` returns without exception, then `clear_region_progress_for_date`. `save_processed_date` is **dead code** (defined, never called).
- Retry: SOAP ConnectionError/Timeout — infinite retry, pause 5→10→…→60 min then reset. Per-request `time.sleep(0.5)` between document types. DB connect: infinite retry every 5s.
- Documentation links: XML xpath from `required_tags/*.json`, insert into `links_documentation_44_fz` / `links_documentation_223_fz`. 223 xpath `.//document` is a **per-XML-file** scan, not a SQL full-table scan. Wall-time share: UNKNOWN (no timers).

## S13 backfill (B)

- Same `main.py` tree under `/opt/tendermonitor` (not assumed identical; see hashes)
- Env config: `/opt/tendermonitor/backward/config.ini`
- `TENDERMONITOR_STOP_BEFORE=2021-01-01` (unit) overrides config `runtime.stop_before_date=2026-04-01`
- EIS via `eis-s7-gateway-forward.service` (`socat` 127.0.0.1:8080 → S7:8080)
- Cursor observed: backward `[eis] date=2026-08-11`; region_progress keys `2026-07-22` (25), `2026-08-11` (3)

## Duplicate code

33/35 active Python files were byte-identical at import time. Intentional remaining diff:

`database_work/contract_registry_locator.py` `find_in_fz_one_query` UNION ALL branches:

- S7: `WHERE contract_number = %s LIMIT 1`
- S13: `WHERE contract_number = %s`

Do not unify in this WIP.

`config.py` + `config/settings.py` exist beside package `config/` (which `main.py` actually imports). Classified LEGACY_SHADOWED commercial-app config. Left in tree as present on disk; not required by EIS `main.py`.

## Extra / not imported

Hundreds of diagnostic scripts, `document_processor/` copy on S7, `nsi_client.py`, `daily_status_migration.py`. Not copied. S7 `tests/test_nsi_regions.py` (live EIS) and `tests/test_status_migration.py` (mutates DB) copied as DIAGNOSTIC only — not part of the safe pytest gate.

## Hash authority (this import)

Canonical `eis_ingestion/s7_forward` ↔ S7 `/opt/tendermonitor` active files: YES at tarball copy.
Canonical `eis_ingestion/s13_backfill` ↔ S13 `/opt/tendermonitor` active files: YES at tarball copy, plus empty package `__init__.py` files that exist on S13 but were missed by the packer (empty / identical to S7).
Contour C `document_processor/daemon.py` + `task_pipeline.py`: NO match (S13 `a4fa1581…` / `3093c987…` vs canonical `dfb97cd1…` / `c389a5d8…`). Not this missing tendermonitor source.
