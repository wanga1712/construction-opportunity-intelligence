# S7_S13_CODE_DIFF

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

Live S13 `/opt/tendermonitor` has **no** `rgk_batch.py`, `rgk_record.py`, `rgk_plan.py`, `rgk_dirty.py`, `rgk_batch_sql.py`, `rgk_batch_store.py`. Backward still uses the pre-batch serial RGK path.

Git tree `eis_ingestion/s13_backfill/` likewise lacks those modules. Proven S7 files to port later (not copied yet):

- `parsing_xml/rgk_record.py`
- `parsing_xml/rgk_batch.py`
- `database_work/rgk_dirty.py`
- `database_work/rgk_batch_sql.py`
- `database_work/rgk_plan.py`
- `database_work/rgk_batch_store.py`

Do not copy forward date/cursor logic. Keep backward `DATE N → N-1`, `TENDERMONITOR_DIRECTION=backward`, backward region checkpoints, and S13 unit.

IDENTICAL_FILES / DIFFERENT_FILES census is deferred to the port PR once those modules exist on S13. Current fact: **S7_ONLY** = the RGK batch stack; **S13_ONLY** = backward config/env/progress paths.
