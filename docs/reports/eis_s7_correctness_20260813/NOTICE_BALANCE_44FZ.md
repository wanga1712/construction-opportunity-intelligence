# NOTICE_BALANCE_44FZ

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
Corpus: forensic re-download of `2026-08-13` PRIZ notices. Classifier uses production admission: `extract_okpd_code` + `collection_codes_okpd` + `purchaseObjectInfo` + `purchaseNumber`.

## Balance (unique identities)

```
44_NOTICE_RAW_UNIQUE = 5630
= PRESENT_IN_REGISTRY 1134
+ INTENTIONALLY_FILTERED_OKPD 4330
+ INTENTIONALLY_FILTERED_EMPTY_TITLE 166
+ DUPLICATE_VERSION (files only, not identities) 76 extra files
+ SOURCE_NOT_RETURNED 0
+ SOURCE_ERROR 0
+ PARSER_ERROR 0
+ UNEXPLAINED_MISSING 0
```

| Field | Value |
|---|---|
| 44FZ_NOTICE_RAW_UNIQUE | 5630 |
| 44FZ_NOTICE_PRESENT | 1134 |
| 44FZ_NOTICE_FILTERED | 4496 (4330 OKPD + 166 empty `purchaseObjectInfo`) |
| 44FZ_NOTICE_SOURCE_ERRORS | 0 |
| 44FZ_NOTICE_UNEXPLAINED_MISSING | **0** |
| 44FZ_NOTICE_DATA_LOSS_FOUND | **NO** |

Files: 5706 = 5630 unique + 76 extra versions.

## Empty title is the production filter, not a generic `name`

166 identities are `epNotificationEZT2020`. Sample `0810500001826000017`: `purchaseNumber` is present, `purchaseObjectInfo` is **null**. A generic `name` tag exists (`placingWay/name` = «Закупка, осуществляемая в соответствии с частью 12 статьи 93…») but production `parse_reestr_contract_44_fz` skips when `auction_name` from `purchaseObjectInfo` is empty. That is INTENTIONALLY_FILTERED_EMPTY_TITLE.

NOT_IN_REGISTRY (4496) is not data loss: 4330 fail the OKPD allowlist, 166 fail empty title.

All 5706 re-downloaded files were already in `file_names_xml` from the benchmark pass.
