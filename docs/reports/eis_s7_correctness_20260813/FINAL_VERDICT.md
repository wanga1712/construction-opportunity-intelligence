# FINAL_VERDICT

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
Status: **OPEN**. `FINAL` is not PASS. **STOP_S13_OPTIMIZATION=YES**.

S7_BENCHMARK_SOURCE_DATE=2026-08-13  
S7_BENCHMARK_ELAPSED_HOURS=0.976  
S7_PID=3717828 (unchanged; not restarted)

## Speedup

| Field | Value |
|---|---|
| S7_SOURCE_TOTAL_XML (notice journal + new RGK files) | 7235 + 7716 = **14951** |
| S7_FILES_NEWLY_PROCESSED (`file_names_xml` in window) | **15017** |
| S7_FILES_DUPLICATE_SKIPPED (RGK leftover re-scan) | **2384755** journal duplicates |
| ONE_HOUR_SPEEDUP_CAUSE | **VALID_OPTIMIZATION** of leftover GUID skip + batch/index. New GUIDs and notice files were written (15017 names). Not “empty work”. |

The hour is still mostly leftover RGK directory walks (~64% of region wall). That skip is the same publish-id, not a dropped 2026-08-13 GUID.

## Dedup

FILENAME_IS_GLOBALLY_UNIQUE=NO  
FALSE_DEDUP_RISK=NO  

## Completeness / correctness

| Field | Value |
|---|---|
| 44FZ_RAW_UNIQUE (RGK XML numbers) | 7473 |
| 44FZ_ACCOUNTED (RGK files) | 7716 = 1447 registry + 6269 unresolved |
| 44FZ_UNEXPLAINED_MISSING | **0** (RGK only) |
| 44FZ_IDENTITY_MATCH | YES (RGK) / PENDING (notices) |
| 44FZ_PRICE_MATCH | **NO** (8 sampled XML prices still match no registry row) |
| 44FZ_DATES_MATCH | PENDING |
| 44FZ_CONTRACTOR_MATCH | YES (RGK registry hits) |
| 44FZ_OKPD_MATCH | YES (RGK registry hits) |
| 44FZ_LIFECYCLE_MATCH | PARTIAL (duplicate awarded ids) |
| 223FZ_RAW_UNIQUE | 1499 notice numbers |
| 223FZ_ACCOUNTED | 293 found / 1206 not in registry |
| 223FZ_UNEXPLAINED_MISSING | **PENDING** (XML deleted) |
| 223FZ_*_MATCH | PENDING |
| S7_2026_08_13_DATA_COMPLETE | **NO** |
| S7_2026_08_13_DATA_CORRECT | **NO** |
| NO_DATA_LOSS | **NO** (not proven for notices/223; RGK unexplained missing is 0 but price mismatches remain) |

## S13

Not started. Hard gate failed.

Authority check: `tendermonitor-eis-parser-backward.service` is on **S7** (`<S7_SSH_USER>@S7`, user `tendermonitor`, `/opt/tendermonitor`), currently inactive. Code tree in git is `eis_ingestion/s13_backfill/`. Do not invent an S13 parser deploy until S7 correctness PASS and the actual backward runtime host is re-inspected.

QWEN_STARTED=NO  
DOCUMENT_WORKERS_STARTED=NO  
CRM_UI_CHANGED=NO  

## Next in this same WIP

1. Side re-download of 2026-08-13 PRIZ/RI223/615 into `/tmp` (do not touch S7 cursor) and finish notice/223 balance to `UNEXPLAINED_MISSING=0`.
2. Explain or fix the remaining RGK `final_price` mismatches (last XML version vs duplicate awarded ids vs dirty-check).
3. Only then Phase 10+.
