# FULL_SOURCE_DAY_BENCHMARK

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`  
Status: **OPEN**. Do not close until the hard SLA gate below.

S7_FORWARD_BENCHMARK_ONLY=YES  
S13_BACKWARD_INCLUDED_IN_SLA=NO  
QWEN_STARTED=NO  
DOCUMENT_WORKERS_STARTED=NO  
CRM_UI_CHANGED=NO

## Catch-up date (not the SLA benchmark)

`2026-08-12` was already partially processed by the serial RGK path. It is **not** `BENCHMARK_SOURCE_DATE`.

Live 2026-08-17 18:56 MSK: `2026-08-12` is **absent** from `region_progress.json` (cleared). Config cursor moved to `2026-08-13`.

## Candidate clean date

First source-date started at 0/55 by the optimized forward parser:

| Field | Value |
|---|---|
| BENCHMARK_SOURCE_DATE | **candidate** `2026-08-13` |
| BENCHMARK_START | 2026-08-17T18:17:38+03:00 (`source_date_start`, regions_skipped=0, regions_remaining=55) |
| Snapshot | 2026-08-17T18:55:29+03:00 — **35/55** regions in `region_progress` |
| BENCHMARK_FINISH | PENDING |
| BENCHMARK_ELAPSED_HOURS | PENDING |
| 44FZ_CURRENT_DATA_COMPLETE | PENDING |
| 223FZ_CURRENT_DATA_COMPLETE | PENDING |
| ALL_REGIONS_COMPLETE | NO |
| REGION_PROGRESS_CLEARED | NO (key `2026-08-13` still present) |
| NEXT_SOURCE_DATE_STARTED | NO |

Parser PID **3717828** since 16:43:23 MSK (no restart for the index). RGK skip still ~0.2–0.3s / 500.

Orphan `region_progress` keys unrelated to the live cursor: 2025-12-26, 2026-02-18, 2026-04-01, 2026-07-29. They do not count as the SLA date.

## Hard close gate (unchanged)

`FINAL=PASS` only if all of:

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

If that day is still ≥24h: stay in **this** WIP and optimize the next measured S7 forward bottleneck. Do not start Qwen/docs/CRM in this WIP.
