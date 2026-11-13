# Full post-parse normalization durable coverage

Дата: `2026-11-13`

WIP: `WIP_FULL_POST_PARSE_NORMALIZATION_DURABLE_MARKER_AND_77_CARD_REPAIR_V1`

## Result

```text
FROZEN_WITH_ESTIMATE_ROWS=1068
HISTORICAL_COMPLETED_IMPORTED=991
REPAIRED_COHORT=77
STALE_POST_IMPORT_REPAIRED=1
FULL_NORMALIZATION_COMPLETED_AFTER=1068
PARTIAL_AFTER=0
NOT_ATTEMPTED_AFTER=0
```

Historical coverage is based only on APPLIED reports, plan SHA and immutable row
ID/coverage evidence. `category_code` was not used to prove normalization.

## Durable authority

```text
NORMALIZER_VERSION=estimate_row_taxonomy_resolver_v1

RUN_TABLE=estimate_row_normalization_runs
PROCUREMENT_COVERAGE_TABLE=estimate_row_normalization_procurements

ROWSET_FINGERPRINT=input_row_count,input_max_row_id,input_rows_sha256
STALE_STATE=IMPLEMENTED
NEW_VERSION_REQUIRES_RERUN=YES
```

Historical run:

```text
RUN_ID=1
STATUS=COMPLETED
PROCUREMENTS=991
ROWS_EXPECTED=916039
ROWS_EXAMINED=916039
PROOF_SOURCE=HISTORICAL_APPLIED_REPORT
```

Frozen target:

```text
RUN_ID=2
STATUS=PARTIAL
PROCUREMENTS=77
PARTIAL=50
NOT_ATTEMPTED=27
```

## Target dry run

```text
RUN_ID=4
CARDS=77
ROWS_EXPECTED=405504
ROWS_EXAMINED=405504
MATCHED=2312
UNMATCHED=403192
PLANNED_UPDATES=1682
PLAN_SHA256=2495a6649af5fd4856de0491b86bcc1b83f3eefceb259f15bf3b6b828c87a956
```

First dry-run attempt `run_id=3` failed because of a report constant typo. It is
preserved as `FAILED`; it made no category writes.

## Write canary

Cohort: `5 PARTIAL + 5 NOT_ATTEMPTED`.

```text
RUN_ID=6
CARDS=10
ROWS=11383
UPDATED=3
CATEGORY_ROWS_BEFORE=112
CATEGORY_ROWS_AFTER=115
SUBCATEGORY_ROWS_BEFORE=56
SUBCATEGORY_ROWS_AFTER=59
COVERAGE=10/10
DB_DOSSIER_POSITION_PARITY=10/10
```

## Remaining cohort

```text
RUN_ID=8
CARDS=67
ROWS_EXPECTED=394121
ROWS_EXAMINED=394121
UPDATED=1679
PLAN_SHA256=7cddfc0de84ba30bcaf2a5146754047a65ffb11f3de22d6615acbf198c544a31
```

After historical and target passes, card `484885` correctly became `STALE`
because 90 rows appeared after its imported fingerprint. A separate repair run
examined all `394` current rows and restored `COMPLETED`.

## Dossier correction

Production `load_category_positions()` was missing. The reviewed insertion was
released to:

```text
/opt/CRM_Streamlit/src/services/procurement_card_dossier_service.py
/opt/CRM_Streamlit/src/services/procurement_card_category_service.py
```

The reader now uses canonical `structured_estimate_rows`, not
`structured_entities`. For all 10 canary cards, every DB preferred position
tuple `(row_id, category_code, subcategory_code)` matched the dossier.

Backup:
`/opt/CRM_Streamlit/backups/dossier_estimate_positions_20261113_173641`

## ZERO_MATCH quality

Sample:

```text
ZERO_MATCH_COHORT=764
SAMPLE_CARDS=50
SAMPLE_ROWS=100
SIZE_BUCKETS=17 small / 17 medium / 16 large

Z2_MATERIAL_LIKE_NO_TERM_MATCH=89
Z3_BLOCKED_BY_NEGATIVE_TERM=2
Z6_SUBCATEGORY_SIGNAL_ONLY=9

SAMPLE_OBVIOUS_MISSES=2
```

Both obvious misses are:

```text
Мастика битумно-масляная МБ-50
```

The row has `waterproofing/coating` and
`waterproofing/polymer_coatings` candidates with term `мастика`, but semantic
guard rejects it.

```text
ZERO_MATCH_RESOLVER_QUALITY=NEEDS_REPAIR
TRUE_BUSINESS_ZERO_CONFIRMED=NO
```

## Kiosk

The old Firefox page was reloaded via one `s13-kiosk.service` restart.

Visual acceptance screenshot:
`docs/reports/full_normalization_durable_marker_20261113/kiosk_after_reload_20261113.png`

```text
Сегодня поступило=38
Требуют обработки=17
Без коммерческого сигнала=21
Обработано=17
Осталось=0
Routing backlog=0
Document queue pending=0
KIOSK_VISUAL_PASS=YES
```

## Tests and deployment

```text
TESTS=26
TEST_RESULT=PASS
```

Runtime hashes:

```text
estimate_row_normalization_authority.py
93e2d051141067c331f6cc097d22e43a5b463d3700aa70efde99f54d77036823

resolve_estimate_row_categories.py
59930cbf302a93fb335ced123c3a50e5a6f00643e4f850c142d76e0868d59b8f

backfill_normalization_authority.py
31271a4e8d6c40135023aad1d3448730dcdfe4d34b0e64da8f75e81372c02ff9

procurement_card_dossier_service.py
05b9155f04c5faee3c26df2da1a69d926cf8d6f056d7d76b9002c6daf8e56abc

procurement_card_category_service.py
c39f206c6948e8a917e98e2c06ff326a6f89eab02564b81182523a28ac78f1a9
```

## Next

```text
NEXT_WIP=WIP_ESTIMATE_ROW_TAXONOMY_COVERAGE_REPAIR_V1
```

Repair should target context-sensitive `мастика` and other
`Z2_MATERIAL_LIKE_NO_TERM_MATCH` cases without inferring category value or
medals.
