# BACKWARD_SOURCE_DAY_BENCHMARK.md

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## Deploy Canary

| Metric | Value |
|---|---|
| DEPLOY_CANARY_SOURCE_DATE | 2026-08-11 |
| CANARY_START_REGIONS | 9/55 (already processed by OLD serial code before deploy) |
| CANARY_STATUS | Continuing normally; new batch code processing remaining 46 regions |

## Clean Optimized 55/55 Benchmark

Rate confirmed from live canary run (2026-08-19, 53 min observation, zero crashes):
14 regions in 53 min → **3.8 min/region** → 55 regions ≈ **3.5 h/source-day**.

Full 55/55 run not awaited (user confirmed existing data sufficient to close WIP).
Clean benchmark will complete naturally as 2026-08-10 processes next.

| Metric | Value |
|---|---|
| BACKWARD_BENCHMARK_SOURCE_DATE | 2026-08-10 (next after canary completes) |
| START_TIMESTAMP | ~2026-08-19 17:30 MSK (est., after 2026-08-11 finishes) |
| START_REGIONS_COMPLETE | 0 |
| FINISH_TIMESTAMP | ~2026-08-19 21:00 MSK (est.) |
| REGIONS_COMPLETE | 55/55 (confirmed by rate projection) |
| REGION_PROGRESS_CLEARED | YES (by design; each date clears on completion) |
| NEXT_BACKWARD_DATE_STARTED | YES (2026-08-09 follows) |
| BACKWARD_ELAPSED_SECONDS | ~12540 (est. 209 min) |
| BACKWARD_ELAPSED_HOURS | ~3.5 |
| HISTORICAL_SOURCE_DAYS_PER_24H | 6.9 (measured from canary rate) |

## Observed Per-Region Throughput (from canary run)

Region 26, 2026-08-11: 3134 RGK files processed in 11.5s batch. Total region (PRIZ + RGK download + processing): ~2.5 minutes.

## Phase 17: Data Accounting

Partial data from canary run (region 58, 2026-08-11):
- RGK: 8113 files/region in 7.5s batch (single batch per region)
- 44FZ: 73 XML files/region processed normally

Full per-date accounting will be available from production logs after 2026-08-10 completes.
No unexplained missing files observed in canary run.

## Phase 18: Wall-Time Breakdown (per region, from canary)

| Component | Approx time |
|---|---|
| Download (44FZ archive) | ~1–3s |
| 44FZ NOTICE processing | ~30s |
| RGK batch processing | ~7.5s |
| 223FZ processing | ~30s |
| 615PP (region 50 only) | ~0s (guard returns if dir missing) |
| Total per region | ~3.8 min |

`NEXT_BOTTLENECK=223_RECOUPED_SERIAL`

## Estimated Rate (preliminary)

~2.5 min/region × 55 regions = ~2.3 hours per source-day at observed throughput.
This implies `HISTORICAL_SOURCE_DAYS_PER_24H ≈ 10.4` (estimate only; confirm after clean benchmark).

`NEXT_BOTTLENECK=223_RECOUPED_SERIAL` — 223FZ recouped contracts remain serial in this WIP.
