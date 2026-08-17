# RGK correctness parity

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

Gate: `python -m pytest eis_ingestion/tests/test_rgk_batch.py eis_ingestion/tests/test_s7_recovery_opts.py eis_ingestion/tests/test_import_closure.py eis_ingestion/tests/test_source_day_sla.py -q`

Result: **21 passed** (2026-08-17).

| Case | Result |
|---|---|
| existing awarded / identical RGK | UPDATE skipped |
| awarded / changed final_price | one UPDATE on awarded |
| awarded / changed contractor | one UPDATE on awarded |
| changed execution dates | UPDATE start+end |
| main → awarded | promote from main |
| unclear → awarded | promote from unclear |
| canonical new contract | INSERT main, real title, okpd_id set |
| missing OKPD → unresolved | no INSERT, `MISSING_OKPD_ID` |
| repeated unresolved, same payload | no UPSERT |
| duplicate filename | skip, filename not re-marked |
| multiple versions same contract in one batch | last write wins, one UPDATE, both filenames marked |
| null → value | UPDATE |
| 223 mappings | unchanged (`test_223_mapping_invariants_unchanged`) |
| S13 locator | still not unified with S7 |

`FINAL_TABLE_MATCH=YES` (plan destinations: awarded stays awarded; promote only from promotable sources).  
`FINAL_FIELDS_MATCH=YES` (dirty fields + COALESCE so NULL incoming does not clear).  
`PROMOTION_MATCH=YES` (contractor_id AND delivery_end_date, 44-FZ only).  
`UNRESOLVED_MATCH=YES`.  
`NO_DATA_LOSS=YES` (DB failure rolls back filenames with business rows; corrupt XML logged).

Parse-once: `parse_rgk_file` returns `parse_passes=1`. Persistence does not re-read XML.
