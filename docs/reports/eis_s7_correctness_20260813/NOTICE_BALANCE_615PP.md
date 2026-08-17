# NOTICE_BALANCE_615PP

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

Production: regions 50/77 only; no OKPD filter; skip if empty `commonInfo/regNum` or empty `purchaseSubjectInfo/name` (`auction_name`). `hydro_filter_strict` defaults false, so missing hydro keywords is not a skip.

## Balance (unique identities)

```
615_RAW_UNIQUE = 64
= PRESENT 41
+ FILTERED_EMPTY_TITLE 23
+ extra version files 2
+ UNEXPLAINED_MISSING 0
```

| Field | Value |
|---|---|
| 615_RAW_UNIQUE | 64 |
| 615_PRESENT | 41 |
| 615_FILTERED | 23 |
| 615_UNEXPLAINED_MISSING | **0** |

Prefix split on disk: 41 `pprf615Contract` (registry hits) + 24 `pprf615ContractProcedure` + 1 cancel. Procedure XML has `commonInfo/regNum` but **no** `purchaseSubjectInfo/name` (execution/procedure payload, not the procurement with work kind). Production skips empty auction_name. That is not `links_documentation_615_pp` failure and not a missing procurement row.

All 66 files were in `file_names_xml` from the benchmark window.
