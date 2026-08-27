# IMPLEMENTATION AND PRODUCTION ACCEPTANCE

**WIP:** `CRM-V3-EXPERT-OBJECT-AND-PROCUREMENT-MODE-STAGED-ANNOTATION-1`  
**Date:** 2026-08-26  
**Baseline (GitHub HEAD at start):** `4010e77ecd55f7a0ab3fbc53a7e38398fb92a793`  
**Deployed runtime at start (S13):** `b9c45be1f1c76c295f99d8bd1a0af2e1f95df253`

**IMPLEMENTATION_COMMIT:** `8696b561ef18dce6a93beffe34ed8a7d4b3a6a35`  
**CLOSURE_COMMIT:** (docs closure pending push; see final response)  
**DEPLOYED_RUNTIME_COMMIT:** `afa14edcfdcbf4c5c2a0ed8bcbed8858bfa0f26a`

## Summary

Staged expert annotation on Analytics Contour cards:

1. **SOURCE** — factual read-only contour from `source_table` (44/223/615/commercial tokens only).
2. **OBJECT** — controlled `expert_object_sector` → `expert_object_type` → optional subtype.
3. **PROCUREMENT MODE** — `expert_procurement_mode` ∈ PROJECT / WORKS / PROJECT_AND_WORKS / DIRECT_SUPPLY / UNCERTAIN.
4. **PRODUCT CATEGORY GATE** — preserved `expert_category_scope` + multiselect.

No medal redesign. No model/prompt/AI-queue/DDL changes.

## Phase 1 — Object authority audit (production)

| Item | Result |
|------|--------|
| EXISTING_OBJECT_SECTOR_AUTHORITY | None in expert payload historically; model heuristics are **not** vocabulary authority |
| EXISTING_OBJECT_TYPE_AUTHORITY | Free-text `expert_object_type`; HUMAN suggestions via `collect_expert_object_types` |
| EXISTING_OBJECT_SUBTYPE_AUTHORITY | Free-text `expert_object_subtype` |
| EXISTING_OBJECT_VALUES_COUNT | 0 current expert rows with object/mode fields (fresh stage) |
| NEW AUTHORITY | `expert_object_taxonomy.py` — 7 sectors, 30 types, 7 optional subtypes |

## SERVICES edge case

`SERVICES_MODE_REQUIRED=NO`

Production has ~37 service-ish titles (обслуживание / содержание / обследование / сервис / эксплуатац), often mixed with works/design. No business control mandates a separate SERVICES mode; operators use WORKS or UNCERTAIN.

## Source contour

| Code | Law label | Contour |
|------|-----------|---------|
| 44-FZ | 44-ФЗ | Государственная / муниципальная закупка |
| 223-FZ | 223-ФЗ | Корпоративная закупка |
| 615-PP | 615-ПП | Капитальный ремонт МКД |
| COMMERCIAL | Коммерческая | Коммерческая закупка (only if source_table tokens support it) |

Production source_tables observed: `reestr_contract_44_fz`, `reestr_contract_44_fz_awarded`, `reestr_contract_223_fz` (no 615 in inventory sample).

## Performance

- NEW_PER_CARD_SQL_FOR_SOURCE_CONTOUR=0
- NEW_PER_CARD_SQL_FOR_OBJECT_TAXONOMY=0

## Tests

- Local: 50 passed (category gate + staged + state + workbench + stage workspace)
- S13: 27 passed (venv313)
- Real route AppTest: PASS, exceptions=0
  - After «Разметить →»: object question, procurement-mode radio, category question, source banner all visible

## Runtime

- SERVICE_ACTIVE=active
- HTTP_STATUS=200

## Non-change boundaries

MODEL_CHANGED=NO, PROMPT_CHANGED=NO, MODEL_INPUT_CHANGED=NO, AI_QUEUE_CHANGED=NO, HISTORICAL_BOT_CHANGED=NO, DOCUMENT_RESOLVER_CHANGED=NO, MEDAL_LOGIC_CHANGED=NO, DDL_CHANGED=NO

## Next WIP (do not start)

`CRM-V3-EXPERT-PRODUCT-CATEGORY-AND-COMMERCIAL-MEDAL-STAGE-1`
