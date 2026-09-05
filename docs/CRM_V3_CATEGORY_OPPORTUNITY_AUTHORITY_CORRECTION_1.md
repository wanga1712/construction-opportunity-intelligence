# Feature Specification: CRM-V3-CATEGORY-OPPORTUNITY-AUTHORITY-CORRECTION-1

## 1. Goal & Context

This specification defines the authority correction for multi-category commercial opportunity cards and read model.
It corrects the previous foundation (`97eb8d9`) by:
1. Identifying the exact commercial authority layer (`crm_procurement_category_opportunities` and `crm_v3_expert_annotations`).
2. Ensuring `CATEGORY_MEDAL_FROM_RESEARCH_PRIOR = NO` — raw Stage 1 `research_prior_band` is NEVER copied into category `commercial_medal`.
3. Ensuring `INDEPENDENT_CATEGORY_MEDALS = YES` — category medals are read independently per category from commercial/expert authority.
4. Eliminating hardcoded states (`COMMERCIAL_STATE_HARDCODED = NO`, `MEDAL_AUTHORITY_HARDCODED = NO`).
5. Joining `structured_entities` to fetch live `quantity_value`, `quantity_unit`, `unit_price`, `total_price`, and `product_relation`.
6. Enforcing strict NMCK upper bound safety (`MULTI_CATEGORY_DIRECT_NMCK_DUPLICATION = 0`) so NMCK upper bound is ONLY used when scope is `DIRECT_GOODS` AND confirmed category count == 1.

## 2. Authority Definition

```text
COMMERCIAL_AUTHORITY={
  CATEGORY_RELATION_TABLE: crm_procurement_category_opportunities (crm db) / crm_v3_expert_annotations (crm db)
  CATEGORY_ID: commercial_category_code
  PROCUREMENT_ID: procurement_id

  COMMERCIAL_ENTRY_COLUMN: expert_commercial_entry (in crm_v3_expert_annotations.payload)
  COMMERCIAL_MEDAL_COLUMN: current_effective_medal (in crm_procurement_category_opportunities) / expert_medal (in crm_v3_expert_annotations.payload)
  COMMERCIAL_MEDAL_AUTHORITY: EXPERT_ANNOTATION | MODEL_PROMOTED | UNANNOTATED
  EXPERT_CONFIRMATION_COLUMN: confirmed_base_medal / is_current (in crm_v3_expert_annotations)

  STRUCTURED_ENTITY_TABLE: structured_entities (document_intelligence db)
  ENTITY_CATEGORY_LINK: category_code, subcategory_code, detail_id
  QUANTITY_VALUE: quantity_value
  QUANTITY_UNIT: quantity_unit_normalized / quantity_unit_raw
  UNIT_PRICE: unit_price_value
  TOTAL_PRICE: total_price_value

  DOCUMENT_EVIDENCE_LINK: detail_id -> document_match_details.id (document_intelligence db)
}
```

## 3. Acceptance Criteria

- `REMOTE_HEAD_CORRECT = YES`
- `CATEGORY_MEDAL_FROM_RESEARCH_PRIOR = NO`
- `COMMERCIAL_STATE_HARDCODED = NO`
- `MEDAL_AUTHORITY_HARDCODED = NO`
- `COMMERCIAL_CATEGORY_AUTHORITY_IDENTIFIED = YES`
- `STRUCTURED_FACTS_ACTUALLY_JOINED = YES`
- `LIVE_QUANTITY_ROWS_GT_0 = YES`
- `MULTI_CATEGORY_DIRECT_NMCK_DUPLICATION = 0`
- `STAGE1_MEDAL_UNCHANGED = YES`
- `SERVICE_BAND_UNCHANGED = YES`
- `TARGETED_FAILED = 0`
