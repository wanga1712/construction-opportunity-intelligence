# IMPLEMENTATION AND PRODUCTION ACCEPTANCE

**WIP:** `CRM-V3-EXPERT-PRODUCT-CATEGORY-AND-COMMERCIAL-MEDAL-STAGE-1`
**Date:** 2026-08-27
**Baseline (GitHub HEAD at start):** `8a9642418ca266c7e51101e462a633d98e22f828`
**Deployed runtime at start (S13):** `6b382993d6767805beabb651526479b064a71dec`

## Phase 1 — Medal / commercial audit

| Item | Result |
|------|--------|
| CURRENT_EXPERT_MEDAL_VALUES | GOLD, SILVER, BRONZE, WOOD, NCE (legacy) |
| CURRENT_MODEL_MEDAL_VALUES | GOLD, SILVER, BRONZE, WOOD (CandidateMedal; no NCE) |
| CURRENT_COMMERCIAL_VERDICT_VALUES | expert_commercial_verdict ACTIONABLE / NO_COMMERCIAL_ENTRY |
| CURRENT_NCE_SEMANTICS | No Commercial Entry — fake medal / legacy marker, not CandidateMedal |
| CURRENT_GOLD_SEMANTICS | Высокий коммерческий потенциал / точно стоит отрабатывать |
| CURRENT_SILVER_SEMANTICS | Наш объект, коммерчески интересен |
| CURRENT_BRONZE_SEMANTICS | Потенциально интересен, но есть ограничения |
| CURRENT_WOOD_SEMANTICS | В категории и коммерчески подходит, но слабый / низкий приоритет |
| MANAGER_PUBLICATION | Unchanged — gates on opportunity commercial_state, not expert_medal |

## Implemented

1. Product category + subcategory (crm_product_categories / crm_product_subcategories)
2. expert_commercial_entry in COMMERCIAL / NON_COMMERCIAL / UNCERTAIN (not source contour)
3. Human medal GOLD-WOOD only when COMMERCIAL
4. OUT_OF_CATEGORY fast path: no category/commercial/medal
5. NON_COMMERCIAL: no medal required
6. Card summary + staged dataset + PARTIAL model comparison
7. Filters for commercial / non-commercial

## Performance

- NEW_PER_CARD_SQL_FOR_PRODUCT_TAXONOMY=0
- NEW_PER_CARD_SQL_FOR_COMMERCIAL_STATE=0

## Non-change boundaries

MODEL/PROMPT/INPUT/AI_QUEUE/DOCUMENT/PUBLICATION/SOURCE_CONTOUR/DDL = NO

## Next

MANUALLY_ANNOTATE_30_TO_40_REAL_CARDS
