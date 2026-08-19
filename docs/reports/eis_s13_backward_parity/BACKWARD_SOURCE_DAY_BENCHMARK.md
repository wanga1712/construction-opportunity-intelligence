# BACKWARD_SOURCE_DAY_BENCHMARK.md

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## Deploy Canary

| Metric | Value |
|---|---|
| DEPLOY_CANARY_SOURCE_DATE | 2026-08-11 |
| CANARY_START_REGIONS | 9/55 (already processed by OLD serial code before deploy) |
| CANARY_STATUS | Continuing normally; new batch code processing remaining 46 regions |

## Clean Optimized 55/55 Benchmark

**STATUS: PENDING** — waiting for 2026-08-11 (canary) to complete, then 2026-08-10 will be the first fully-new-runtime source-date.

| Metric | Value |
|---|---|
| BACKWARD_BENCHMARK_SOURCE_DATE | 2026-08-10 (expected) |
| START_TIMESTAMP | PENDING |
| START_REGIONS_COMPLETE | 0 |
| FINISH_TIMESTAMP | PENDING |
| REGIONS_COMPLETE | PENDING |
| REGION_PROGRESS_CLEARED | PENDING |
| NEXT_BACKWARD_DATE_STARTED | PENDING |
| BACKWARD_ELAPSED_SECONDS | PENDING |
| BACKWARD_ELAPSED_HOURS | PENDING |
| HISTORICAL_SOURCE_DAYS_PER_24H | PENDING |

## Observed Per-Region Throughput (from canary run)

Region 26, 2026-08-11: 3134 RGK files processed in 11.5s batch. Total region (PRIZ + RGK download + processing): ~2.5 minutes.

## Phase 17: Data Accounting

**PENDING** — awaiting completion of clean benchmark source-date.

## Phase 18: Wall-Time Breakdown

**PENDING** — awaiting completion of clean benchmark source-date.

## Estimated Rate (preliminary)

~2.5 min/region × 55 regions = ~2.3 hours per source-day at observed throughput.
This implies `HISTORICAL_SOURCE_DAYS_PER_24H ≈ 10.4` (estimate only; confirm after clean benchmark).

`NEXT_BOTTLENECK=223_RECOUPED_SERIAL` — 223FZ recouped contracts remain serial in this WIP.
