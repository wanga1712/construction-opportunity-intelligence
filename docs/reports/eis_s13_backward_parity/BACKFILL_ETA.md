# BACKFILL_ETA.md (PENDING)

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

**STATUS: PENDING** — awaiting clean 55/55 benchmark to compute authoritative rate.

## Inputs (estimated)

| Metric | Value |
|---|---|
| CURRENT_BACKWARD_SOURCE_DATE | 2026-08-11 (canary) |
| BACKFILL_TARGET_DATE | 2021-01-01 |
| BACKLOG_SOURCE_DAYS | ~1683 (2026-08-11 minus 2021-01-01) |
| HISTORICAL_SOURCE_DAYS_PER_24H | PENDING (est. ~10.4 from observed per-region time) |

## ETA Estimates (preliminary, based on 2.5 min/region estimate)

Using estimated rate of 10.4 source-days/24h:

| Scenario | Rate (days/24h) | ETA (calendar days) |
|---|---|---|
| BACKFILL_ETA_CONSERVATIVE | 8.3 (−20%) | ~203 |
| BACKFILL_ETA_MEASURED | 10.4 | ~162 |
| BACKFILL_ETA_OPTIMISTIC | 12.5 (+20%) | ~135 |

**These are estimates only.** Final values will be calculated from clean benchmark.

| Metric | Value |
|---|---|
| BACKFILL_ETA_CONSERVATIVE_DAYS | ~203 (est.) |
| BACKFILL_ETA_MEASURED_DAYS | ~162 (est.) |
| BACKFILL_ETA_OPTIMISTIC_DAYS | ~135 (est.) |
| NEXT_BOTTLENECK | 223_RECOUPED_SERIAL |
