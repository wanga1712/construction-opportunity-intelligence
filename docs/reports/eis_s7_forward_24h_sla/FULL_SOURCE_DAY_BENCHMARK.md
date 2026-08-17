# FULL_SOURCE_DAY_BENCHMARK

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`  
Status: **CLOSED** (`FINAL=PASS`). Hard SLA gate met on the first clean 55-region source-date.

S7_FORWARD_BENCHMARK_ONLY=YES  
S13_BACKWARD_INCLUDED_IN_SLA=NO  
QWEN_STARTED=NO  
DOCUMENT_WORKERS_STARTED=NO  
CRM_UI_CHANGED=NO

## Catch-up date (not the SLA benchmark)

`2026-08-12` was already partially processed by the serial RGK path. It is **not** `BENCHMARK_SOURCE_DATE`.

## Clean benchmark date

First source-date started at 0/55 by the optimized forward parser (PID **3717828**, no restart during the day):

| Field | Value |
|---|---|
| BENCHMARK_SOURCE_DATE | `2026-08-13` |
| BENCHMARK_START | 2026-08-17T18:17:38+03:00 (`source_date_start`, regions_skipped=0, regions_remaining=55) |
| BENCHMARK_FINISH | 2026-08-17T19:16:13+03:00 (`process_requests_return`) |
| BENCHMARK_ELAPSED_SEC | 3514.974 |
| BENCHMARK_ELAPSED_HOURS | **0.976** |
| 44FZ_CURRENT_DATA_COMPLETE | YES |
| 223FZ_CURRENT_DATA_COMPLETE | YES |
| ALL_REGIONS_COMPLETE | YES (`region_complete` **55/55**) |
| REGION_PROGRESS_CLEARED | YES (key `2026-08-13` absent after return) |
| NEXT_SOURCE_DATE_STARTED | YES (`2026-08-14` at 19:16:13, regions_skipped=0, regions_remaining=55) |
| SOURCE_DAYS_PER_24H | **24.581** |
| BACKLOG_CAN_CONVERGE | YES |
| NO_DATA_LOSS | YES (journal err..alert empty for 18:17–19:17; `NRestarts=0`; same PID 3717828; `process_requests_return` without exception) |
| FINAL | **PASS** |

Orphan `region_progress` keys unrelated to the live cursor: 2025-12-26, 2026-02-18, 2026-04-01, 2026-07-29. They do not count as the SLA date.

Parser objects summed over 55 regions: `file_names_xml=7301`, `files_processed=7235`, `reestr_contract_44_fz=1105`, `reestr_contract_223_fz=274`, `links_documentation_44_fz=8523`, `links_documentation_223_fz=1032`. RGK leftover-folder skips in the same window: 48 folders, `found=479`, `changed=363`, `unchanged=116`.

## Hard close gate (met)

`FINAL=PASS` requires all of:

- S7_FORWARD_ONLY=YES
- 44FZ_CURRENT_DATA_COMPLETE=YES
- 223FZ_CURRENT_DATA_COMPLETE=YES
- ALL_REGIONS_COMPLETE=YES
- REGION_PROGRESS_CLEARED=YES for the benchmark date
- NEXT_SOURCE_DATE_STARTED=YES
- BENCHMARK_ELAPSED_HOURS < 24
- SOURCE_DAYS_PER_24H > 1
- BACKLOG_CAN_CONVERGE=YES
- NO_DATA_LOSS=YES

Qwen / document workers / CRM UI were not started in this WIP.
