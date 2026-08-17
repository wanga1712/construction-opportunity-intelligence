# RGK batch design — S7 forward 44-FZ

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

S13 backward is out of scope. 223-FZ recouped stays on the existing per-file path.

## Problem

The live 44-FZ RGK/recouped path was:

```
XML → parse → SELECT registry → SELECT OKPD → SELECT contractor
    → UPDATE → COMMIT → file_names_xml INSERT → COMMIT → next XML
```

Audit (`12bf230`): ~2500 SELECTs, ~2000 COMMITs, ~2 XML parse passes per 1000 RGK; 70–90% UPDATEs redundant; ~3.6 UPDATE/s.

## New path

```
500 XML names
  → bulk filename lookup
  → parse unknown XML once into RGKRecord
  → bulk OKPD / contractor / registry / unresolved lookups
  → dirty-check
  → batch UPDATE / INSERT / UPSERT / promote
  → bulk filename insert
  → one COMMIT
```

Transaction boundary: **one batch → one commit**. Default `RGK_BATCH_SIZE=500`, env `TENDERMONITOR_RGK_BATCH_SIZE`, clamped 100–2000.

Filename is marked processed only in the same transaction as business persistence.

## Modules

| Module | Role |
|---|---|
| `parsing_xml/rgk_record.py` | Parse XML once. No DB. |
| `database_work/rgk_dirty.py` | Null-safe dirty-check on the six required fields. |
| `database_work/rgk_batch_sql.py` | SQL builders + lifecycle merge. |
| `database_work/rgk_plan.py` | Pure plan: found/changed/unchanged/insert/unresolved/promote. |
| `database_work/rgk_batch_store.py` | Bulk execute + single commit. |
| `parsing_xml/rgk_batch.py` | Folder orchestrator. |
| `parsing_xml/okpd_parser.py` | Dispatch 44-FZ recouped folder to batch; 223 unchanged. |

`okpd_parser.py` is 557 lines (already >450 before this WIP). Growth is a short dispatch branch only; batch logic lives in the new modules (all ≤377 lines).

## Lifecycle (unchanged)

Lookup order: main → commission_work → unknown → unclear → awarded. Completed is not searched.

- existing awarded → update awarded
- main / commission / unclear / unknown → update → promote when contractor_id and delivery_end_date are present
- not found + canonical okpd_id + real title → insert into main
- otherwise → `rgk_contract_unresolved`
- non-target OKPD with no registry row → unresolved `MISSING_OKPD_ID` (same as before)

Dirty-check fields: `final_price`, `contractor_id`, `delivery_start_date`, `delivery_end_date`, `auction_name`, `okpd_id`. Incoming NULL does not overwrite. Identical row → `UPDATE=SKIP`.

## Logging

Per-contract INFO removed from updater/promoter (debug only). One aggregate INFO line per RGK batch.

## Forbidden

- multiprocessing / thread pool / parallel regions
- rollback to `4f415376`
- S13 code or service changes
- 223 mapping changes (`submissionCloseDateTime`, execution dates, `contractData/price`, purchase notice number)
