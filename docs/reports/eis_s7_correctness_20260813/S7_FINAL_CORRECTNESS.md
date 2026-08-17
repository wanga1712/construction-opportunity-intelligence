# S7_FINAL_CORRECTNESS

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
S7 PID during this proof: **3717828** (not restarted).

## Gate

| Field | Value |
|---|---|
| S7_BENCHMARK_SOURCE_DATE | 2026-08-13 |
| S7_BENCHMARK_ELAPSED_HOURS | 0.976 |
| S7_SOURCE_TOTAL_XML | 7301 notices+615 on re-download flatten + 7716 new RGK = **15017** window names |
| S7_FILES_NEWLY_PROCESSED | 15017 |
| S7_FILES_DUPLICATE_SKIPPED | 2384755 RGK leftover journal skips |
| FILENAME_IS_GLOBALLY_UNIQUE | NO |
| FALSE_DEDUP_RISK | NO |
| 44FZ_NOTICE_RAW_UNIQUE | 5630 |
| 44FZ_NOTICE_PRESENT | 1134 |
| 44FZ_NOTICE_FILTERED | 4496 |
| 44FZ_NOTICE_UNEXPLAINED_MISSING | **0** |
| 223FZ_NOTICE_RAW_UNIQUE | 1499 |
| 223FZ_NOTICE_PRESENT | 293 |
| 223FZ_NOTICE_FILTERED | 1206 |
| 223FZ_NOTICE_UNEXPLAINED_MISSING | **0** |
| 615_RAW_UNIQUE | 64 |
| 615_PRESENT | 41 |
| 615_FILTERED | 23 |
| 615_UNEXPLAINED_MISSING | **0** |
| REGION32_REDOWNLOAD_OK | YES |
| REGION32_SOURCE_XML_MISSED_DURING_BENCHMARK | NO |
| RGK_NEW_XML | 7716 |
| RGK_ACCOUNTED | 7716 |
| RGK_UNEXPLAINED_MISSING | 0 |
| PRICE_MISMATCHES_TOTAL | 8 |
| PRICE_MISMATCHES_EXPLAINED | 8 |
| PRICE_MISMATCHES_REAL_DEFECTS | 1 (C, isolated DB replay + git sort fix) |
| 44FZ_IDENTITY_MATCH | YES (RGK + notices vs production filter) |
| 44FZ_PRICE_MATCH | YES |
| 44FZ_DATES_MATCH | YES (2 live start diffs are later leftover overwrites after the window) |
| 44FZ_CONTRACTOR_MATCH | YES (RGK registry hits) |
| 44FZ_OKPD_MATCH | YES (RGK registry hits) |
| 44FZ_LIFECYCLE_MATCH | YES with debt |
| DUPLICATE_AWARDED_ROW_DEBT | 73 numbers among window registry hits |
| 223FZ_NOTICE_IDENTITY_MATCH | YES vs production filter |
| 223FZ_DATES_MATCH | YES (292/293 first-file; the one miss is v2 vs v3 `submissionCloseDateTime`) |
| S7_2026_08_13_DATA_COMPLETE | **YES** |
| S7_2026_08_13_DATA_CORRECT | **YES** |
| NO_DATA_LOSS | **YES** |
| ONE_HOUR_SPEEDUP_CAUSE | **VALID_OPTIMIZATION** |

## Technical debt (not 08-13 loss)

- 223 `purchaseNoticeAESMBO` uses `purchaseNoticeAESMBOData`; tags still say `purchaseNoticeData`. 134 OKPD-matching AESMBO skipped as empty contract_number.
- Duplicate awarded rows for the same `contract_number`.
- RGK last-write-wins used filename order; git now sorts by EIS version/publish/GUID. Production `/opt/tendermonitor` was **not** restarted; only contract `0315100000526000418` was replay-updated.

## S13

S7 correctness gate is closed. Backward optimization is now allowed. Runtime stays on S13; DB stays on S7.
