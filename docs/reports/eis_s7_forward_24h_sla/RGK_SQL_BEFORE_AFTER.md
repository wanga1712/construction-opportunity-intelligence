# RGK SQL before / after

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

Baseline from audit `12bf230` (live S7, serial awarded UPDATE+COMMIT):

| Metric per 1000 RGK | Old | New target | New bound (batch 500 × 2) |
|---|---|---|---|
| SELECT statements | ≈2500 | ≤50 | 18 |
| COMMIT statements | ≈2000 | ≤5 | 2 |
| XML parse passes | ≈2000 | 1000 | 1000 (unknown files only) |
| UPDATE statements | ≈1000 | ≤20 | 2 (one `UPDATE … FROM VALUES` per destination table per batch) |
| Unchanged UPDATE rows | 70–90% | 0 | 0 by dirty-check |

## Old SQL shape

- 1 UNION lookup per contract (`find_in_fz_one_query`)
- 1 `collection_codes_okpd` SELECT per OKPD code until hit
- 1 contractor SELECT per XML with INN
- 1 `UPDATE … WHERE id = %s` + COMMIT per changed-or-not row
- 1 `INSERT file_names_xml` + COMMIT per file

## New SQL shape (one batch of 500)

1. `SELECT file_name FROM file_names_xml WHERE file_name = ANY(%s)`
2. `SELECT id, sub_code FROM collection_codes_okpd WHERE sub_code = ANY(%s)`
3. `SELECT id, inn FROM contractor WHERE inn = ANY(%s)`
4. Up to 5 registry lookups, lifecycle order, `WHERE contract_number = ANY(%s)`, remaining numbers shrink after each table
5. `SELECT … FROM rgk_contract_unresolved WHERE fz_type = %s AND contract_number = ANY(%s)`
6. Missing contractors: INSERT with SAVEPOINT (unique INNs only)
7. Canonical INSERTs for new contracts
8. `UPDATE <table> AS t SET … COALESCE(v.col, t.col) FROM (VALUES %s) AS v(…) WHERE t.id = v.id`
9. Promote: `INSERT INTO awarded SELECT * FROM source WHERE id = ANY(%s)` + replica DELETE
10. Unresolved `INSERT … ON CONFLICT DO UPDATE` only for new/changed payloads
11. Bulk links + bulk filenames
12. **one COMMIT**

Registry merge preserves lookup priority exactly: first table in `lookup_order` wins.

Builders: `eis_ingestion/s7_forward/database_work/rgk_batch_sql.py`.
