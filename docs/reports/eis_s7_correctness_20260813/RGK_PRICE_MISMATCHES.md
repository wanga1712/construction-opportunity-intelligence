# RGK_PRICE_MISMATCHES

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

Canonical order: EIS `versionNumber`, then publish timestamp (UTC), then filename GUID. Not DB id, not mtime, not glob order.

`PRICE_MISMATCHES_TOTAL=8` were **8 first-row sample rows** (7 unique `contract_number`; `0160300003626000356` appeared twice with two stale XML prices).

Benchmark window: `2026-08-17T18:17:38+03:00`–`19:16:13+03:00` (= `15:17–16:16 UTC`). Live S7 continued `2026-08-14` after that; later `updated_at` is **not** an 08-13 parser skip.

## Classification

| # | contract_number | Class | Evidence |
|---|---|---|---|
| 1 | `0172200004926000387` | **A** | Two 08-13 XML; later publish 21:42 price `65494.06` = main DB. Audit compared 16:20 `130988.11`. |
| 2 | `0373200315425000007` | **A** | v2 later GUID `019FFB50` price `235436.05` = awarded. Audit compared v1 `378212.01`. |
| 3 | `0373200333526000009` | **A** | 08-13 later XML `87172.80` matched DB at any-row audit. Live now `33118.80` from leftover GUID `01A0009D…` (`updated_at` 17:03 UTC, after the window). |
| 4–5 | `0160300003626000356` | **A** | Three 08-13 XML; latest publish `62134.00` = main. Audit compared `18563.40` and `31067.00`. |
| 6 | `0315100000526000418` | **C** then **fixed** | Same version 0; later publish/GUID `019FFA79` price `25706116.47`, earlier `019FFA6C` price `25523736.57` written last (filename order). Isolated replay updated awarded id 657049 → `25706116.47`. Production cursor not changed; S7 PID 3717828 not restarted. |
| 7 | `0351400001326000392` | **A** | 08-13 v0 `130374.00`. Live `130372.39` is leftover v1 GUID `019FFFA3…` (`updated_at` 16:45 UTC, after window). |
| 8 | `0348100013126000155` | **A** | 08-13 v0 `26257.00`. Live `26254.00` is leftover v1 GUID `019FFEAA…` (`updated_at` 16:40 UTC, after window). |

| Field | Value |
|---|---|
| PRICE_MISMATCHES_TOTAL | 8 |
| PRICE_MISMATCHES_EXPLAINED | **8** |
| PRICE_MISMATCHES_REAL_DEFECTS | **1** (C: last-write-wins by filename) |
| 44FZ_PRICE_MATCH | **YES** after isolated replay of the C row; remaining samples are stale-XML or later source-day |

## Code fix (git, not deployed to `/opt/tendermonitor` this pass)

`plan_44_batch` now sorts records by canonical EIS order before last-write-wins. `process_44_rgk_folder` parses new files, sorts, then applies batches so cross-batch filename order cannot resurrect an older publish. Regression: `test_canonical_source_order_beats_filename_order` (including timezone-normalised publish). S7 production still runs the previous binary until an explicit forward deploy; the one affected 08-13 row was corrected in DB.
