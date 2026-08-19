# BACKFILL_ETA.md

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## Rate Measurement

Measured during canary run (2026-08-19, PID 4116871, stable for 53 min without restart):
- Regions processed in 53 min: 14 (from 25 to 39 out of 55)
- Average: **~3.8 min/region**
- Full source-day (55 regions): 55 × 3.8 ≈ **209 min ≈ 3.5 hours**
- `HISTORICAL_SOURCE_DAYS_PER_24H = 1440 / 209 ≈ 6.9`

Note: this is a conservative real-world measurement including download time, 44FZ/RGK/223FZ/615PP processing and DB writes. No restarts occurred during measurement window.

## Inputs

| Metric | Value |
|---|---|
| CURRENT_BACKWARD_SOURCE_DATE | 2026-08-11 (canary) |
| BACKFILL_TARGET_DATE | 2021-01-01 |
| BACKLOG_SOURCE_DAYS | 1682 (2026-08-10 → 2021-01-01) |
| HISTORICAL_SOURCE_DAYS_PER_24H | 6.9 (measured) |

## ETA

| Scenario | Rate (days/24h) | ETA (calendar days) |
|---|---|---|
| BACKFILL_ETA_CONSERVATIVE (−20%) | 5.5 | ~306 |
| BACKFILL_ETA_MEASURED | 6.9 | ~244 |
| BACKFILL_ETA_OPTIMISTIC (+20%) | 8.3 | ~203 |

| Metric | Value |
|---|---|
| BACKFILL_ETA_CONSERVATIVE_DAYS | 306 |
| BACKFILL_ETA_MEASURED_DAYS | 244 |
| BACKFILL_ETA_OPTIMISTIC_DAYS | 203 |
| NEXT_BOTTLENECK | 223_RECOUPED_SERIAL |
