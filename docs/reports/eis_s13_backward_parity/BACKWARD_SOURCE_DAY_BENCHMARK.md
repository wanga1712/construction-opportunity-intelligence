# BACKWARD_SOURCE_DAY_BENCHMARK.md

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## Deploy Canary (2026-08-11)

| Metric | Value |
|---|---|
| DEPLOY_CANARY_SOURCE_DATE | 2026-08-11 |
| CANARY_2026_08_11_REGIONS_COMPLETE | 55/55 |
| CANARY_REGION_PROGRESS_CLEARED | YES |
| NEXT_DATE_STARTED | 2026-08-10 |

## Clean Optimized 55/55 Benchmark (ACTUAL)

| Metric | Value |
|---|---|
| BACKWARD_BENCHMARK_SOURCE_DATE | 2026-08-10 |
| START_TIMESTAMP | 2026-08-19 17:00:57 MSK |
| START_PID | 4116871 |
| START_REGIONS_COMPLETE | 0 |
| FINISH_TIMESTAMP | 2026-08-19 20:10:37 MSK |
| REGIONS_COMPLETE | 55/55 |
| REGION_PROGRESS_CLEARED | YES |
| NEXT_BACKWARD_DATE_STARTED | YES (2026-08-09 at 20:10:37) |
| BACKWARD_ELAPSED_SECONDS | 11380 |
| BACKWARD_ELAPSED_HOURS | 3.16 |
| HISTORICAL_SOURCE_DAYS_PER_24H | 7.6 |

Evidence: log line `Прогресс обработки регионов для даты 2026-08-10 очищен` at 20:10:37, immediately followed by `Начало обработки даты 2026-08-09`. Service ran continuously (PID 4116871, no restarts).

## Phase 17: Data Accounting (2026-08-10, from production logs)

| Metric | Value |
|---|---|
| RGK_BATCHES | 53 |
| RGK_XML (input to batches) | 12261 |
| RGK_UNEXPLAINED_MISSING | 0 |
| 44_NOTICE_UNEXPLAINED_MISSING | 0 |
| 223_NOTICE_UNEXPLAINED_MISSING | 0 |
| 615_UNEXPLAINED_MISSING | 0 |
| NO_DATA_LOSS | YES |

No DB errors, FK errors, or unhandled exceptions observed during benchmark window.

## Phase 18: Wall-Time Breakdown

Full source-day wall time: 3.16 hours (11380 seconds).
Dominant paths: 44FZ notice download+parse, RGK batch (53 batches, 12261 files), 223FZ serial recouped.

`NEXT_BOTTLENECK=223_RECOUPED_SERIAL`
