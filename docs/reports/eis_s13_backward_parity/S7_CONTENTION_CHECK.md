# S7_CONTENTION_CHECK.md

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## Phase 13: S7 Contention Watch (optimized backward active)

Measured ~5 minutes after backward restart, with first RGK batch complete.

| Metric | Baseline (serial) | With Optimized Backward |
|---|---|---|
| S7_LOAD | 0.31 / 0.31 / 0.44 | 0.39 / 0.33 / 0.37 |
| POSTGRES_ACTIVE_CONNECTIONS | 1 | 1 |
| POSTGRES_TOTAL_CONNECTIONS | 12 | 10 |
| POSTGRES_TX_RATE (cumulative) | 153,208,523 | 153,210,117 |
| POSTGRES_LOCKS | 33 | 65 |
| S7_FORWARD_STATUS | Active (processing) | Active (waiting for new data) |

Lock count increase from 33→65 is expected at batch commit time (batch of 3134 files). Immediately after commit, locks return to baseline. No sustained lock pressure observed.

## Forward Protection Assessment

| Check | Result |
|---|---|
| S7_FORWARD_PROGRESS_CONTINUES | YES |
| S7_FORWARD_DEGRADATION | NO |
| S7_DB_CONTENTION_FROM_BACKWARD | NO |
| S7_FORWARD_24H_SLA_AT_RISK | NO |

S7 forward progressed normally through 2026-07-29 (50/55 → completed) and is now waiting for 2026-08-16 data. No forward degradation observed.

## Phase 14: Batch Size Tuning

Initial production batch size was the full region folder (3134 files in one batch for region 26). This completed in 11.5s without any observed contention or lock pressure. No tuning required.

| Metric | Value |
|---|---|
| FINAL_RGK_BATCH_SIZE | region-folder (all files per region per subsystem) |
| TUNING_REQUIRED | NO |
