# IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE

WIP: `CRM-V3-EXPERT-CATEGORY-GATE-AND-FIRST-STAGE-DATASET-1`  
Date: 2026-08-26

```
BASELINE_COMMIT=54780848f5bbb835a73616dfea147304c96d69db
DEPLOYED_RUNTIME_AT_START=ec3561513a6e954414e27128e90184d7d8385268
```

## Phase 1 — existing negative semantics

```
CURRENT_NEGATIVE_STORAGE_SEMANTICS=
  OUT_OF_PROFILE shortcut sets expert_scope_verdict=OUT_OF_PROFILE,
  expert_commercial_verdict=NO_COMMERCIAL_ENTRY, expert_medal=NCE,
  error_reasons=[OUT_OF_PROFILE]; classified as NOT_INTERESTING

CURRENT_NEGATIVE_FIELDS=
  expert_scope_verdict, expert_commercial_verdict, expert_medal,
  error_reasons, annotation_review_scope, rejection_reason (per opp)

LEGACY_NEGATIVE_TOTAL=14 (global current annotations; torgi-workset subset later 5)
LEGACY_REASON_NOT_OUR_PRODUCT_OR_WORK=0
LEGACY_REASON_NOT_OUR_OBJECT=0
LEGACY_REASON_NOT_OUR_STAGE=0
LEGACY_REASON_OTHER=14
LEGACY_REASON_MISSING=0
```

No mass conversion of legacy negatives.

## Phase 2 — storage contract (no DDL)

```
CATEGORY_SCOPE_FIELD=expert_category_scope
CATEGORY_CODES_FIELD=expert_category_codes
CATEGORY_SCOPE_VALUES=IN_CATEGORY,OUT_OF_CATEGORY,UNCERTAIN
```

Stored inside `crm_v3_expert_annotations.payload` JSONB.

Authority: `expert_category_scope`.  
Stage-1 NO does **not** set OUT_OF_PROFILE / NCE / NO_COMMERCIAL_ENTRY.

## Phase 3–6 — UI

Primary card gate question:

`Относится ли закупка к нашим товарным категориям?`

- YES → canonical multiselect from `crm_product_categories` (name primary, code secondary)
- NO → `⛔ Вне товарных категорий` + optional comment + Save&Next (no object/stage/medal/docs)
- UNCERTAIN → persists UNCERTAIN without OUT_OF_PROFILE

Visible facts: title, ОКПД2, № закупки remain on card.

## Phase 7 — legacy

Filter: `Старые «Неинтересные»`  
Fast reclassify: Вне товарных категорий / другая причина→UNCERTAIN / Не уверен / reopen YES.

## Phase 8 — counters

```
Все / Не проверено / Проверено / Вне товарных категорий / Старые «Неинтересные»
ALL = UNREVIEWED + REVIEWED
REVIEWED = expert_category_scope exists
```

## Phase 9 — dataset view

Expander on Идут торги: first-stage rows with title/OKPD/scope/codes.

## Phase 11–13 — model

`CURRENT_MODEL_STAGE1_COMPARISON=PARTIAL`  
(no clean native IN/OUT/UNCERTAIN; derived only when opportunities or OUT_OF_PROFILE present)

No training.

## Future pipeline (documented)

1. Title+OKPD → category gate  
2. IN_CATEGORY → object type  
3. work stage  
4. commercial medal  
5. documents/evidence  

This WIP implements stage-1 only.

## Tests

`tests/test_annotation_category_gate.py` + updated state/workspace presentation tests: **23 passed** on S13.

## Production

Service active / HTTP 200 after deploy of category-gate modules.
