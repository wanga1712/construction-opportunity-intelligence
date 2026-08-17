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
| 223FZ_NOTICE_IDENTITY_MATCH | **PENDING** (XML gone; 1206 numbers not in registry, OKPD filter not proven from source) |
| 223FZ_CONTRACT_IDENTITY_MATCH | PENDING |
| 223FZ_PRICE_MATCH | PENDING |
| 223FZ_DATES_MATCH | PENDING |
| 223FZ_PURCHASE_CONTRACT_LINK_MATCH | PENDING |

Mappings in code were not changed in this WIP (`submissionCloseDateTime`, execution dates, `contractData/price`, `purchaseNoticeNumber`). Live field proof needs a side re-download.

Region 32: journal `Connection aborted` on `RI223 purchaseNoticeOA`. Treat as a possible incomplete contour until retry is shown.
