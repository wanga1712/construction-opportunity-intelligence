# REPLAY_BENCHMARK

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

Filename lookup against S7 `tender_monitor` from S13 (500 names, `EXPLAIN ANALYZE`):

| Field | Value |
|---|---|
| FILE_NAME_INDEX_PRESENT | YES (`idx_file_names_xml_file_name`) |
| FILE_NAME_INDEX_USED | YES |
| BACKWARD_FILENAME_LOOKUP_MS | 50.74 |

No duplicate index created.

## Old vs new statement budget (batch=500)

From `statements_for_batch` / unit tests (same planner as S7):

| | OLD serial estimate | NEW batch |
|---|---:|---:|
| SELECTS per 500 XML | ~2500 | ≤ ~9 registry+lookup statements + filename ANY() |
| COMMITS per 500 XML | ~500 | 1 |

Local 3-file fixture wall times are not a throughput proof (parse-bound, milliseconds). Meaningful live NEW_WALL_SECONDS on the 500-file `/tmp/eis_s13_parity/rgk` copy requires running Git `s13_backfill`, not live S7 `rgk_record.py`.

OLD_SELECTS / OLD_COMMITS / NEW_SELECTS / NEW_COMMITS for a 500-file folder:

- OLD_SELECTS=2500 estimate
- OLD_COMMITS=500 estimate
- NEW_SELECTS_EST=9
- NEW_COMMITS_EST=1
- REPLAY_SPEEDUP (DB roundtrips) ≈ 500× fewer commits, not yet measured as wall-clock on the 500-file copy
