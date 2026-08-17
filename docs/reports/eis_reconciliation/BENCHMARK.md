# SOURCE_DAY_24H_SLA and 2026-08-12 benchmark

Measured 2026-08-17 ~14:36 Europe/Moscow. No optimization. No invented rates.

## Completion semantics

SOURCE_DAY_24H_SLA: a publication/date cohort is COMPLETE only when the **forward** contour has finished `EISRequester.process_requests` for every remaining region of that date without exception, then `clear_region_progress_for_date` removes the date from `region_progress.json`.

Not sufficient:

- `[eis] date` cursor moved (`update_config_date` runs **before** work)
- date listed in `processed_dates.json` (`save_processed_date` has **zero callers**)

Retry/completion: SOAP connect/timeout retries indefinitely (5–60 min cycle) inside a region; the date is not complete until every region callback has run and `process_requests` returns.

## 2026-08-12 (S7 forward)

Operator START: **2026-08-16 18:54 Europe/Moscow**.

Journal 18:54–19:05: PID `2355645` live recouped 44-FZ updates / `MISSING_OKPD_ID` blocks. No line `Начало обработки даты 2026-08-12` recovered (full-journal grep timed out; current `debug.log` has only three `2026-08-12` lines). START remains the operator timestamp.

`processed_dates.json`: 25 dates, last `2025-11-12`, **does not contain 2026-08-12**.

`region_progress.json` mtime 2026-08-17 09:27:41 MSK; key `2026-08-12` processed_regions **N=4**: `1`, `10`, `15`, `16`.

`debug.log` (current file):

- 2026-08-17 01:05:08 — region 10 saved for 2026-08-12
- 2026-08-17 09:27:41 — region 16 saved for 2026-08-12
- region 1 / 15 timestamps: UNKNOWN (not in current debug.log; likely rotated)

Cursor `[eis] date=2026-08-12`.

Service restart ExecStart **2026-08-17 12:05:20 MSK** PID `3611797`. From **12:05:19** `debug.log`/`errors.log`: `password authentication failed for user "postgres"`, retry every 5s, still looping at 14:36. Region progress frozen since 09:27. This WIP did not restart the parser and did not change credentials.

FINISH: not reached  
ELAPSED at 14:36 MSK: ~19h 42m from operator START  
CURRENT_PROGRESS: 4 regions checkpointed; total region universe UNKNOWN (`get_region_codes()` needs DB; parser itself cannot authenticate)  
REMAINING_IF_MEASURABLE: UNKNOWN (total unknown); at least 1 region remains because the date key was not cleared  

24h window end: 2026-08-17 18:54 MSK (still open at measurement)  
**24H_SLA=IN_PROGRESS** (will not PASS while hung; do not project PASS)

SOURCE_DAYS_PER_24H: **0 completed** in the observed window (the measured day is still open)

## Throughput

| Metric | Value |
|---|---|
| 44_FZ processed/inserted/updated/exact_repeats per hour | UNKNOWN |
| 223_FZ processed/inserted/updated/exact_repeats per hour | UNKNOWN |
| retry count | SOAP retries: not counted in logs; DB auth retries ~every 5s since 12:05 (1792 `password authentication failed` lines in current debug.log) |
| error count | journal ERROR-like on S13 backfill 1588 in ~20h (mostly customer IntegrityError); S7 forward dominated by DB auth fail after 12:05 |
| HTTP requests / elapsed | UNKNOWN |
| DB queries / elapsed | UNKNOWN |
| parse elapsed | UNKNOWN |
| documentation-link elapsed | UNKNOWN |
| repeat cache hits/misses/hit rate | UNKNOWN |
| `files_skipped_already_processed` | never incremented in current `process_okpd_file` (IntegrityError on `file_names_xml` returns None, parse continues) |
| RGK exact-version cache | in-process `OrderedDict` in `xml_parser_recouped_contract.py`; hit rate UNKNOWN (0 lines in current debug.log) |

Orphan `region_progress` keys on S7 (not the live cursor): 2025-12-26 (2), 2026-02-18 (26), 2026-04-01 (18), 2026-07-29 (50). Daemon does not return to them; it continues `[eis] date`.

OLDEST_UNPROCESSED_SOURCE_DATE (live cursor): **2026-08-12**  
OLDEST_ORPHAN_REGION_PROGRESS_KEY: **2025-12-26**  
BACKLOG_DAYS vs yesterday 2026-08-16: **5** source days (12 in progress + 13–16 not started)

P50/P95/max source→stored latency: **UNKNOWN**

## Bottlenecks (measured only)

PRIMARY_MEASURED_BOTTLENECK: **DB** — authentication failure reconnect loop from 2026-08-17 12:05:19, zero region progress after 09:27.

SECONDARY_MEASURED_BOTTLENECK: **recouped/RGK contract sync** — at operator START the journal is recouped update / `MISSING_OKPD_ID`, not HTTP or links_documentation timing. Wall-time % of `links_documentation_223_fz`: UNKNOWN (xpath `.//document` per XML file; no timer). Exact-repeat file fast path: **inactive**. Do not optimize in this WIP.

REQUIRED_SPEEDUP: UNKNOWN (no completed source day in the window)

Capacity vs 1 new day/day: **C — still accumulate backlog**. Evidence: 0 source days completed in ~20h; cursor 2026-08-12 while yesterday is 2026-08-16; parser hung on DB auth.
