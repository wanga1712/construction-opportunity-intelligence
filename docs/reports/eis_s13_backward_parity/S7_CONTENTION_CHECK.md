# S7_CONTENTION_CHECK

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

Pre-deploy baseline while S7 forward was running and S13 backward (old serial) was already writing to S7:

| Field | Value |
|---|---|
| S7_FORWARD_SERVICE_ACTIVE | YES |
| S7_FORWARD_PID | 3827083 |
| S7_FORWARD_SOURCE_DATE | 2026-08-17 |
| S7_FORWARD_REGION_PROGRESS | leftover keys present (`2026-02-18`, `2025-12-26`, `2026-04-01`, `2026-07-29`); current date 2026-08-17 |
| S7_LOAD_BASELINE | 0.62 0.40 0.62 |
| POSTGRES_CPU_BASELINE | 10.1 (sum `ps -C postgres pcpu`) |
| POSTGRES_PROC_COUNT | 12 |
| S7 backward unit | inactive/disabled |

S7_FORWARD_PROGRESS_CONTINUES was YES at inspect (service active, date 2026-08-17). Post-deploy contention watch is **not** applicable until S13 optimized code is deployed.

No multiprocessing / extra writer processes were enabled.
