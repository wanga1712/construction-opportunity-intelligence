# IMPLEMENTATION AND PRODUCTION ACCEPTANCE

**WIP:** `CRM-V3-EXPERT-OBJECT-AND-PROCUREMENT-MODE-STAGED-ANNOTATION-1`  
**Date:** 2026-08-26  
**Baseline (GitHub HEAD at start):** `4010e77ecd55f7a0ab3fbc53a7e38398fb92a793`  
**Deployed runtime at start (S13):** `b9c45be1f1c76c295f99d8bd1a0af2e1f95df253`

## Summary

Staged expert annotation on Analytics Contour cards:

1. **SOURCE** — factual read-only contour from `source_table` (44/223/615/commercial tokens only).
2. **OBJECT** — controlled `expert_object_sector` → `expert_object_type` → optional subtype.
3. **PROCUREMENT MODE** — `expert_procurement_mode` ∈ PROJECT / WORKS / PROJECT_AND_WORKS / DIRECT_SUPPLY / UNCERTAIN.
4. **PRODUCT CATEGORY GATE** — preserved `expert_category_scope` + multiselect.

No medal redesign. No model/prompt/AI-queue/DDL changes.

## Phase 1 — Object authority audit

| Item | Result |
|------|--------|
| EXISTING_OBJECT_SECTOR_AUTHORITY | None in expert payload historically; model heuristics in `object_mode_routing.classify_object` are **not** vocabulary authority |
| EXISTING_OBJECT_TYPE_AUTHORITY | Free-text `expert_object_type` in JSONB; suggestions via `collect_expert_object_types` (HUMAN only) |
| EXISTING_OBJECT_SUBTYPE_AUTHORITY | Free-text `expert_object_subtype`; same HUMAN suggestion path |
| NEW AUTHORITY | Config module `expert_object_taxonomy.py` (7 sectors, 30 types, 7 optional subtypes) |

## SERVICES edge case

`SERVICES_MODE_REQUIRED=NO`

Reason: primary vocabulary omits SERVICES; model `SERVICES_OTHER` / service titles exist, but no business control mandates a separate human mode. Map to WORKS or UNCERTAIN until an explicit later decision.

## Storage (no DDL)

Additive JSONB keys: `expert_object_sector`, `expert_object_type`, `expert_object_subtype`, `expert_procurement_mode`; existing category gate fields preserved.

## Performance

- NEW_PER_CARD_SQL_FOR_SOURCE_CONTOUR=0
- NEW_PER_CARD_SQL_FOR_OBJECT_TAXONOMY=0

## Tests

Local annotation/stage suite: 50 passed.  
Real route: `scripts/_staged_annotation_apptest.py` on S13 after deploy.

## Non-change boundaries

MODEL_CHANGED=NO, PROMPT_CHANGED=NO, MODEL_INPUT_CHANGED=NO, AI_QUEUE_CHANGED=NO, HISTORICAL_BOT_CHANGED=NO, DOCUMENT_RESOLVER_CHANGED=NO, MEDAL_LOGIC_CHANGED=NO, DDL_CHANGED=NO

## Next WIP (do not start)

`CRM-V3-EXPERT-PRODUCT-CATEGORY-AND-COMMERCIAL-MEDAL-STAGE-1`
