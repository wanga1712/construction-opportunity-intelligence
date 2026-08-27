# IMPLEMENTATION AND PRODUCTION ACCEPTANCE

**WIP:** `CRM-V3-EXPERT-FAST-CATEGORY-TRIAGE-AND-POSITIVE-ONLY-DEEP-ANNOTATION-1`  
**Date:** 2026-08-27  
**Baseline (GitHub HEAD at start):** `b32c6ab79213d73cc563b44825e4872d93c920f6`  
**Deployed runtime at start (S13):** `c5db3addd5e7bdf20c4f8b4d92cf9f917985075f`  
**Implementation commit:** `c9868f553073f7948af67c4c93cfae82e4f8fbbf`  
**Deployed runtime (S13 overlay):** `c9868f553073f7948af67c4c93cfae82e4f8fbbf`

## Problem

Large-scale triage (~1800 cards) was blocked: operators had to fill object sector/type and procurement mode before Save&Next even for clear product mismatches (example: fencing works, OKPD `43.29.12.110`, notice `32515489436`).

## Implemented

1. **Primary gate first** on card surface: «Относится ли закупка к нашим товарным категориям?» ✓ Да / ✕ Нет / ? Не уверен.
2. **OUT_OF_CATEGORY one-action:** click Нет → persist sparse payload → Save&Next. No object/mode/category/commercial/medal/comment.
3. **UNCERTAIN fast defer:** same one-action sparse persist; deep fields not required.
4. **IN_CATEGORY only:** deep annotation unfolds in operator order — product category/subcategory → object → procurement mode → commercial entry → medal (if COMMERCIAL).
5. **Completeness separation:** `is_category_triage_complete` vs `is_deep_annotation_complete`; primary counters/filters use triage.
6. **Compact card for OUT/UNCERTAIN:** badge only; blank object/mode/commercial lines not shown.
7. **Filters:** Все / Не проверено / В категории / Вне товарных категорий / Не уверен + IN subset GOLD–WOOD / Коммерчески не подходит + legacy «Старые Неинтересные».
8. **Sparse dataset:** OUT rows with NULL deep fields are valid; `count_stage_datasets()` exposes independent stage counts.
9. **Legacy negatives preserved** until operator reclassifies; OUT path is one-action.

## Pass matrix

| Flag | Result |
|------|--------|
| CATEGORY_GATE_RENDERED_FIRST | YES |
| OUT_OF_CATEGORY_ONE_ACTION_SAVE_NEXT | YES |
| OUT_OF_CATEGORY_REQUIRES_OBJECT | NO |
| OUT_OF_CATEGORY_REQUIRES_PROCUREMENT_MODE | NO |
| OUT_OF_CATEGORY_REQUIRES_CATEGORY | NO |
| OUT_OF_CATEGORY_REQUIRES_COMMERCIAL_ENTRY | NO |
| OUT_OF_CATEGORY_REQUIRES_MEDAL | NO |
| OUT_OF_CATEGORY_REQUIRES_COMMENT | NO |
| UNCERTAIN_FAST_DEFER | YES |
| IN_CATEGORY_REVEALS_DEEP_ANNOTATION | YES |
| CATEGORY_TRIAGE_AND_DEEP_COMPLETENESS_SEPARATED | YES |
| SPARSE_STAGE_DATASET_SUPPORTED | YES |
| OUT_OF_CATEGORY_SPARSE_ROW_VALID | YES |
| LEGACY_NEGATIVE_PRESERVED | YES |
| NEW_PER_CARD_SQL | 0 |
| FAST_TRIAGE_KEYBOARD_SHORTCUTS | NO |
| REAL_ROUTE_NEGATIVE_FAST_PATH | PASS |
| REAL_ROUTE_POSITIVE_DEEP_PATH | PASS |

## Dataset counts (S13 live at acceptance)

| Stage | Count |
|-------|------:|
| CATEGORY_DATASET_COUNT | 0 |
| OBJECT_DATASET_COUNT | 0 |
| MODE_DATASET_COUNT | 0 |
| COMMERCIAL_DATASET_COUNT | 0 |
| MEDAL_DATASET_COUNT | 14 |

Note: medal rows are legacy payload medals without staged `expert_category_scope`. After triage begins, CATEGORY ≥ OBJECT ≥ MEDAL is the expected staged shape for **new** labels.

## Real-route acceptance

- Control notice `32515489436` → CRM id `17084`, title fencing / OKPD `43.29.12.110`.
- Current annotation is **legacy** OUT_OF_PROFILE / NO_COMMERCIAL_ENTRY (not auto-converted).
- Sparse OUT payload validated; DB JSONB accepts NULL deep fields; no production mutation in acceptance.
- AppTest `app.py` → Аналитический контур v2: exceptions **0**; «Идут торги» present.
- Positive deep widgets order proven in source (product → object → mode → commercial/medal).

## Tests

- Local focused: **42 PASS** (`test_fast_category_triage`, staged, category gate, commercial/medal, analytics filters, state service).
- S13 after deploy: **42 PASS** same suite.
- AppTest exceptions: **0**.

## Non-change boundaries

| Boundary | Result |
|----------|--------|
| MODEL_CHANGED | NO |
| PROMPT_CHANGED | NO |
| MODEL_INPUT_CHANGED | NO |
| AI_QUEUE_CHANGED | NO |
| HISTORICAL_BOT_CHANGED | NO |
| PROCUREMENT_SOURCE_PARSER_CHANGED | NO |
| DOCUMENT_RESOLVER_CHANGED | NO |
| MANAGER_PUBLICATION_CHANGED | NO |
| PRODUCT_TAXONOMY_CHANGED | NO |
| MEDAL_SEMANTICS_CHANGED | NO |

## Runtime

- SERVICE_ACTIVE=active
- HTTP_STATUS=200
- DEPLOY method: `git archive` monorepo `crm_streamlit/` overlay onto flat `/opt/CRM_Streamlit` (no monorepo checkout as working tree).

## Next

`MANUAL_FAST_TRIAGE_OF_REAL_PROCUREMENTS`

STOP_AFTER_WIP=YES
