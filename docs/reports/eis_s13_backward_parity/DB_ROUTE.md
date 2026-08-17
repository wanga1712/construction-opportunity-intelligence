# DB_ROUTE

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

Parser DB settings come from `/opt/tendermonitor/database_work/db_credintials.env` (`DB_*_TENDER`), loaded by `DatabaseManager`. Passwords not recorded.

| Field | Value |
|---|---|
| BACKWARD_RUNTIME_HOST | S13 |
| BACKWARD_DB_HOST_ALIAS | S7 |
| BACKWARD_DB_PORT | 5432 |
| BACKWARD_DB_NAME | `tender_monitor` |
| BACKWARD_DB_ROLE | `postgres` (file key `DB_USER_TENDER`) |
| S13_TO_S7_DB_CONNECTION | PASS |

`idx_file_names_xml_file_name` is present and used. Representative 500-name `EXPLAIN (ANALYZE, BUFFERS)`: `FILE_NAME_INDEX_USED=YES`, `BACKWARD_FILENAME_LOOKUP_MS=50.74`. No new index created.

S13 `/opt/tendermonitor/.env` also contains a local catalog-style block. That file is not the `DatabaseManager` path for EIS writes. Do not point backward at S13 PostgreSQL.
