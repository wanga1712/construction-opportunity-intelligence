# SOURCE_DAY_STAGE_TIMING

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

S7_FORWARD_BENCHMARK_ONLY=YES  
S13_BACKWARD_INCLUDED_IN_SLA=NO

2026-08-12 is a **catch-up** date (6/55 regions already done by the serial RGK path before this deploy). Not a clean SLA benchmark.

Live sample after batch deploy (region 20, 2026-08-17 16:43+ MSK):

| Stage | Seconds | Notes |
|---|---|---|
| 44FZ_NOTICE_SECONDS | ~2 | 10 XML, region 20 PRIZ |
| 44FZ_RGK_SECONDS | PENDING | currently skipping already-named XML at ~11s / 500 |
| 223FZ_NOTICE_SECONDS | PENDING | region 20 not finished |
| 223FZ_CONTRACT_SECONDS | PENDING | |
| 615PP_SECONDS | PENDING | |
| SOAP_SECONDS | PENDING | RGK SOAP progress 4/692 on this region |
| DOWNLOAD_SECONDS | ~1 | one RGK zip |
| UNZIP_SECONDS | included in download log | |
| DB_SECONDS | ~11s per 500 known filenames | `file_names_xml WHERE file_name = ANY(%s)` |
| OTHER_SECONDS | PENDING | |

Observed RGK skip rate: 500 files / 11.0s ≈ 45 files/s vs old ~3.6 UPDATE/s. This sample is **all duplicates**, not the dirty-check persist path.

A persist with `found/changed>0` is required before ranking the next bottleneck by wall time of a full source-day.
