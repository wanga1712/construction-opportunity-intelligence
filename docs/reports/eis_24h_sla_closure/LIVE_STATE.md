# LIVE_STATE — S7 EIS parser

WIP: PROJECT-EIS-PRODUCTION-RECOVERY-AND-24H-SOURCE-DAY-SLA-CLOSURE-1

Pre-fix snapshot (before password-file alignment): 2026-08-17T15:00:26+03:00

| Field | Value |
|---|---|
| LIVE_CHECK_TIME | 2026-08-17T15:20:09+03:00 (pre-deploy) |
| SERVICE_ACTIVE | active (`tendermonitor-eis-parser.service`) |
| MAIN_PID (auth-fix restart) | 3672485 since 2026-08-17 15:05:44 MSK |
| MAIN_PID (code deploy) | 3692779 since 2026-08-17 15:21:36 MSK |
| PROCESS_UPTIME (15:20) | 14m24s, CPU 61.7%, RAM 1.5% |
| CURRENT_SOURCE_DATE | 2026-08-12 |
| CURRENT_REGION | in progress after checkpoint 16; region_progress mtime still 2026-08-17 09:27:41 |
| REGIONS_COMPLETE | 4 (`1,10,15,16`) |
| REGIONS_TOTAL | 55 |
| LAST_REGION_PROGRESS_AT | 2026-08-17 09:27:41 |
| DB_CONNECTION_HEALTH | OK after 15:05 credential-file alignment |
| LAST_USEFUL_PROGRESS_AT | 2026-08-17 15:22:49+ (awarded 44-FZ recouped updates) |

Orphan `region_progress` keys not on the live cursor: 2025-12-26 (2), 2026-02-18 (26), 2026-04-01 (18), 2026-07-29 (50). Live cursor is 2026-08-12 only.

Post-deploy metrics JSONL first line:

```json
{"event":"source_date_start","ts":"2026-08-17T15:21:37+03:00","source_date":"2026-08-12","regions_remaining":51,"regions_skipped":4}
```
