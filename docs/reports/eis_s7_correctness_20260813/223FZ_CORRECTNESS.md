# 223FZ_CORRECTNESS

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

Historical awarded reconstruction remains **OUT OF SCOPE**.

223 notice XML for 2026-08-13 was deleted after parse. Independent identities from window filenames only:

| Field | Value |
|---|---|
| 223 notice files | 1529 |
| UNIQUE_PURCHASE_NOTICE_NUMBERS | 1499 |
| FOUND_IN_REGISTRY | 293 |
| NOT_IN_REGISTRY | 1206 |
| 223 RGK leftover on disk | 0 (folder empty; serial path deletes) |
| contractCutted without number | 3577 journal ERROR |

| Gate | Value |
|---|---|
| 223FZ_NOTICE_IDENTITY_MATCH | **YES** vs production filter | 293 present + 1072 OKPD + 134 AESMBO/empty `purchaseNoticeData` |
| 223FZ_DATES_MATCH | **YES** | 292/293 first-file; remaining is v2 vs v3 close datetime |

Mappings in code were not changed (`submissionCloseDateTime`, execution dates, `contractData/price`, `purchaseNoticeNumber`). Side re-download confirmed identity + dates vs the production filter contract.

Region 32: journal `Connection aborted` on `RI223 purchaseNoticeOA`. Independent re-download of OA returned 0 URLs/zips/XML. Other 223 types for region 32: 35 XML, all in `file_names_xml`. Not parser data loss.
