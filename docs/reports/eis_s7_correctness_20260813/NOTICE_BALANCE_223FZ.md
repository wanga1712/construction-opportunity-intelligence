# NOTICE_BALANCE_223FZ

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
Historical awarded reconstruction remains **OUT OF SCOPE**.

Production admission: OKPD allowlist, then `purchaseNoticeData/registrationNumber` as `contract_number`. Empty number → skip (file deleted). Date mapping unchanged: `submissionCloseDateTime` → submission deadline / `end_date`; `documentationDelivery` is not execution period.

## Balance (unique identities)

```
223_NOTICE_RAW_UNIQUE = 1499
= PRESENT_IN_REGISTRY 293
+ INTENTIONALLY_FILTERED_OKPD 1072
+ INTENTIONALLY_FILTERED_INVALID 134
+ extra version files 30
+ SOURCE_NOT_RETURNED 0
+ PARSER_ERROR 0
+ UNEXPLAINED_MISSING 0
```

| Field | Value |
|---|---|
| 223FZ_NOTICE_RAW_UNIQUE | 1499 |
| 223FZ_NOTICE_PRESENT | 293 |
| 223FZ_NOTICE_FILTERED | 1206 (1072 OKPD + 134 invalid/empty production number) |
| 223FZ_NOTICE_SOURCE_ERRORS | 0 |
| 223FZ_NOTICE_UNEXPLAINED_MISSING | **0** |
| 223FZ_NOTICE_IDENTITY_MATCH | **YES** vs production filter contract |

## 134 INVALID

Sample `purchaseNoticeAESMBO_32616289983`: registration number lives under `purchaseNoticeAESMBOData`, not `purchaseNoticeData`. Production xpath does not see it → empty `contract_number` → skip. Downloaded on purpose (`documentType223_RI223` includes AESMBO); current tags do not admit that schema.

`AESMBO_SCHEMA_NOT_IN_TAGS` is **technical debt**, not 2026-08-13 speedup loss. Same tags existed before the batch/index work.

## Region 32

Benchmark: `Connection aborted` on `RI223 purchaseNoticeOA`.  
Side re-download: OA `urls=0 zips=0 xml=0`. Other types: 35 XML, all in `file_names_xml`.

| Field | Value |
|---|---|
| REGION32_REDOWNLOAD_OK | YES |
| REGION32_SOURCE_XML_MISSED_DURING_BENCHMARK | NO |
| SOURCE_NETWORK_FAILURE | YES (OA SOAP abort) with **empty source** on retry |
| PARSER_DATA_LOSS | NO |
