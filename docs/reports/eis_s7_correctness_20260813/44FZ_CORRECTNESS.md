# 44FZ_CORRECTNESS

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## RGK (mandatory path for the batch parser)

All 7716 newly marked `contract_*` files for the window are still on disk and parse with `parse_rgk_file`. Identity from XML `order/notificationNumber` (and filename fallback).

| Gate | Value | Notes |
|---|---|---|
| 44FZ_IDENTITY_MATCH | **YES** (RGK) | 7716/7716 parsed; 0 missing from registry+unresolved |
| 44FZ_OKPD_MATCH | **YES** among registry hits | 1447/1447 OKPD match; 6269 unresolved (typically `MISSING_OKPD_ID`) |
| 44FZ_CONTRACTOR_MATCH | **YES** among registry hits | 1447/1447 |
| 44FZ_LIFECYCLE_MATCH | **PARTIAL** | 978 of 1447 hits sit in awarded; duplicate `contract_number` rows exist in awarded (pre-existing) |
| 44FZ_PRICE_MATCH | **NO** | 24 XML-vs-first-row diffs; 8/15 sampled still mismatch vs **any** row |
| 44FZ_DATES_MATCH | PENDING | not fully aggregated this pass |

Remaining price examples (XML ≠ any registry row): `0172200004926000387` 130988.11 vs 65494.06; `0373200315425000007` 378212.01 vs 235436.05; `0351400001326000392` 130374.00 vs 130372.39 (kopeck). Several other “mismatches” were duplicate awarded rows where a later id already stored the XML price.

Targeted cases:

| Case | Evidence |
|---|---|
| new contract | journal RGK `inserted=873` (batch sum) |
| unchanged | `unchanged=105` |
| changed price/contractor/dates | `changed=339`, `found=444` |
| main → awarded | `promoted=687` |
| unresolved MISSING_OKPD_ID | 6269 window RGK files with unresolved and no live row |
| duplicate RGK versions | 2687 leftover numbers have several GUIDs; skip is per GUID |
| several XML versions in one batch | unit tests already cover last-write-wins; live 24 price leftovers need a follow-up on last-version vs duplicate ids |

## Notices

XML deleted. Filename purchase numbers: 5630 unique, 1134 in registry. Cannot sign `44FZ_IDENTITY_MATCH=YES` for notices until a side re-download of 2026-08-13 PRIZ archives is parsed for OKPD/title filters.
