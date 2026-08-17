# S7_S13_CODE_DIFF

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## Live S13 vs Git (before deploy)

Live `/opt/tendermonitor` still has **no** RGK batch stack. Git `eis_ingestion/s13_backfill/` now contains the proven S7 modules.

S13_MISSING_BATCH_MODULES (live): `rgk_record.py`, `rgk_batch.py`, `rgk_dirty.py`, `rgk_batch_sql.py`, `rgk_batch_store.py`, `rgk_plan.py`  
S13_IDENTICAL_MODULES (Git s7_forward vs s13_backfill, byte-identical): those six plus `source_day_metrics.py`, `database_connection.py`, `monitoring_service.py`, `main.py`, `logger_config.py`  
S13_DIFFERENT_MODULES (Git, expected): `okpd_parser.py` (S13 keeps backward 223 serial dispatch + DEBUG prints; 44 recouped now calls `process_44_rgk_folder`), remaining debug-print noise.

PROVEN_RGK_BATCH_STACK_PRESENT_ON_S13_AFTER (Git)=YES  
PROVEN_RGK_BATCH_STACK_PRESENT_ON_S13_AFTER (live)=NO — not deployed yet.

## Ported from proven S7 (backward semantics preserved)

Copied as-is into `s13_backfill/`:

- parse-once `rgk_record.py`
- bounded batch `rgk_batch.py` (`RGK_BATCH_SIZE` default 500, clamp 100–2000)
- dirty-check `rgk_dirty.py`
- bulk SQL `rgk_batch_sql.py`
- planner `rgk_plan.py` with canonical EIS version/publish/GUID order
- store `rgk_batch_store.py` (one COMMIT per batch)

Also ported connection-reuse that is not forward-date logic:

- `DatabaseOperations(db_manager=)`
- `DatabaseIDFetcher(db_manager=)` shared with parser
- `RecoupedContractSync` reused on `AdvancedXMLParser`
- `find_in_fz_one_query` + parenthesized `LIMIT 1` UNION
- `insert_file_name` IntegrityError rollback so a shared connection is not left aborted
- 615 and notice paths reuse one parser/DB manager

Not copied: forward date increment, forward monitoring wait, forward `stop_before` unused path. Backward remains `DATE N → N-1` via `date_to_process -= timedelta(days=1)`.

## Size note

`okpd_parser.py` is 545 lines after the port. It stays one file because 44/223/615 dispatch and folder identity must remain in one place; splitting it in this WIP would mix notice semantics with the RGK batch cut. Decomposition is out of scope until this WIP closes.
