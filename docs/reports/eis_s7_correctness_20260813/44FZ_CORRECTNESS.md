# 44FZ_CORRECTNESS

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## RGK (mandatory path for the batch parser)

All 7716 newly marked `contract_*` files for the window are still on disk and parse with `parse_rgk_file`. Identity from XML `order/notificationNumber` (and filename fallback).

| Gate | Value | Notes |
|---|---|---|
| 44FZ_IDENTITY_MATCH | **YES** (RGK) | 7716/7716 parsed; 0 missing from registry+unresolved |
| 44FZ_OKPD_MATCH | **YES** among registry hits | 1447/1447 OKPD match; 6269 unresolved (typically `MISSING_OKPD_ID`) |
| 44FZ_CONTRACTOR_MATCH | **YES** among registry hits | 1447/1447 |
| 44FZ_LIFECYCLE_MATCH | **YES** with debt | canonical live row exists; DUPLICATE_AWARDED_ROW_DEBT=73 |
| 44FZ_PRICE_MATCH | **YES** | 8 sample rows explained; 1 C defect replayed to canonical `25706116.47` |
| 44FZ_DATES_MATCH | **YES** | window canonical vs any-row; 2 live start diffs are post-window leftover |

Eight first-row sample mismatches are explained in `RGK_PRICE_MISMATCHES.md` (7 A = stale XML or later leftover; 1 C replayed).

Targeted cases:

| Case | Evidence |
|---|---|
| new contract | journal RGK `inserted=873` (batch sum) |
| unchanged | `unchanged=105` |
| changed price/contractor/dates | `changed=339`, `found=444` |
| main → awarded | `promoted=687` |
| unresolved MISSING_OKPD_ID | 6269 window RGK files with unresolved and no live row |
| duplicate RGK versions | 2687 leftover numbers have several GUIDs; skip is per GUID |
| several XML versions in one batch | last-write-wins is now EIS version/publish/GUID order in git; one C row replayed |

## Notices

XML deleted. Filename purchase numbers: 5630 unique, 1134 in registry. Side re-download classified the rest as 4330 OKPD + 166 empty `purchaseObjectInfo`. `44FZ_NOTICE_UNEXPLAINED_MISSING=0`.
