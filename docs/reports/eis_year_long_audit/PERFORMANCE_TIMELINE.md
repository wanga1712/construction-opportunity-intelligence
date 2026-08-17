# PERFORMANCE_TIMELINE

Historic per-source-day wall-time **cannot be reconstructed** from systemd journal:

- `processed_dates.json` on S7 has 25 stale dates, last `2025-11-12` (`save_processed_date` is dead code).
- Per-contract `logger.info("Обновлён контракт ...")` floods journald; `journalctl --since 2026-08-01 | grep` timed out at 120s.
- `source_day_metrics.jsonl` exists only from 2026-08-17 15:21:37 (one `source_date_start` line).

## Live 3b26815 window (this audit, service not restarted)

| Field | Value |
|---|---|
| START | 2026-08-17 15:21:36 MSK (PID 3692779) |
| SAMPLE | 2026-08-17 15:46:02 MSK |
| ELAPSED | 24.5 min |
| SOURCE_DATE | 2026-08-12 |
| REGIONS_COMPLETED | still 4/55 |
| LOGGED awarded UPDATEs | 3765 |
| LOGGED main-table UPDATEs | 1584 |
| PROMOTES | 0 |
| RATE | ~3.6 logged UPDATEs/s |
| CPU | 75% |
| REGION_PROGRESS_MTIME | still 2026-08-17 09:27:41 |

Normalized: **3.6 RGK UPDATEs per second** on one region, serial, DB+log bound. Region not finished after 24.5 min ⇒ remaining RGK XML in the current region is large.

## Workload-normalized comparison (architecture, not hours)

| VERSION | RGK path | SQL per typical RGK | Skip if already awarded |
|---|---|---|---|
| `4f415376` 2026-02-09 | `get_reestr_contract_44_fz_id` on **main table only** + `_update_existing_contract` | 1 SELECT + 0–1 UPDATE + 1 COMMIT | YES (no row → no update) |
| Uncommitted Jul–Aug 2026 / `5e4dd60` | multi-table UNION lookup + UPDATE wherever found including awarded + unresolved UPSERT + `logger.info` | see DB_ROUNDTRIPS.md | NO — always writes awarded |

Feb path is faster **because it does less lifecycle work**, not because the same work ran quicker.
