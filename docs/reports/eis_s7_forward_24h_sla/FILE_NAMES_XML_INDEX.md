# file_names_xml lookup index

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

S7 `tender_monitor.public.file_names_xml`. Parser was **not** restarted. S13 untouched.

## Audit (read-only)

| Field | Value |
|---|---|
| Owner | `postgres` |
| DDL route | `sudo -n -u postgres psql -d tender_monitor` (S7 analog of documented S13 `sudo -n -u postgres psql`) |
| reltuples | 25_457_928 |
| total / heap / indexes (before new idx) | 3599 MB / 2380 MB / 1219 MB |
| Existing indexes | `file_names_xml_pkey (id)`, `idx_file_names_xml_processed_at (processed_at DESC)` |
| Index on `file_name` before | **none** |
| Unique on `file_name` | **no** |
| Duplicate proof | first seq-scan EXPLAIN returned 33144 rows for 500 names; no UNIQUE constraint |

`COUNT(*)` not used (table too large; previous audit timed out). Estimate from `reltuples`.

## Plan before

`Seq Scan` on `file_name = ANY(500)`. Execution **13803.81 ms**. Shared read 287168 buffers.

## Index

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_file_names_xml_file_name
ON public.file_names_xml USING btree (file_name);
```

Non-unique btree: uniqueness **not** proven (duplicates exist). No dedup/cleanup.

Build ~3.5 min. Parser PID stayed **3717828**.

## Same 500-name probe

File `/tmp/file_names_xml_probe_500.txt` sha256 `2d2bd8119ad259e5764c59716e3ca0535e9dbcbcad8ae48a476a8cb8ca0ed976`

Forced seq scan vs index on that exact list:

| Field | Value |
|---|---|
| RESULT_MATCH | YES (500 rows both ways) |
| INDEX_USED | YES (`Index Only Scan` / `idx_file_names_xml_file_name`) |
| BEFORE_MS | 13792.786 |
| AFTER_MS | 9.577 |

Live RGK skip after index: **~0.3s / 500** (was ~11s). Region 29 folder sample: `files=46464 batches=93 found=14 changed=11 inserted=28 unresolved=143 elapsed=28.0s`.
