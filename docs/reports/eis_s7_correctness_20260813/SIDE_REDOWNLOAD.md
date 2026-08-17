# SIDE_REDOWNLOAD

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
Source-date: `2026-08-13`  
Host: S7 forensic only.

## Isolation

Wrote only under `/tmp/eis_correctness_20260813/`. Did **not** change production cursor, `region_progress.json`, `file_names_xml`, registry tables, or processed-date state. Did **not** restart `tendermonitor-eis-parser.service` (PID **3717828** stayed active). Did **not** touch S13 backward.

Contours: 44-FZ PRIZ notices, 223-FZ RI223 purchase notices, 615-PP. RGK was not re-downloaded (leftover XML still on disk).

## Result

| Field | Value |
|---|---|
| REDOWNLOAD_REGIONS_ATTEMPTED | 55 |
| REDOWNLOAD_REGIONS_COMPLETE | 55 |
| jobs | 611 |
| archives/zips | 293 |
| xml_extracted | 7307 |
| xml unique files on disk after flatten | **7301** (= 5706 + 1529 + 66) |
| DOWNLOAD_ERRORS | 0 |
| MISSING_REGIONS | none |
| REGION32_REDOWNLOAD_OK | **YES** |
| production_writes | NONE |

The 7307 vs 7301 delta is duplicate basenames overwritten when flattening `xml/{contour}/{region}/`. Every one of the 7301 remaining files is present in `file_names_xml` (`not_seen_in_file_names_xml=0`).

## Region 32 / `purchaseNoticeOA`

Independent SOAP for `RI223 purchaseNoticeOA` returned `urls=0 zips=0 xml=0 ok=true`. Benchmark journal `Connection aborted` on that type therefore had **no payload to miss**. Other 223 types for region 32 produced 35 XML (26 `purchaseNotice` + 9 `purchaseNoticeAESMBO`), all processed.

| Field | Value |
|---|---|
| REGION32_SOURCE_XML_AVAILABLE | YES (35 files; OA empty at source) |
| REGION32_SOURCE_XML_MISSED_DURING_BENCHMARK | **NO** |
| REGION32_DB_IDENTITIES_PRESENT | 3 PRESENT + 30 OKPD-filtered + 2 invalid schema |

Raw zips/XML stay in `/tmp/eis_correctness_20260813/` until this WIP closes.
