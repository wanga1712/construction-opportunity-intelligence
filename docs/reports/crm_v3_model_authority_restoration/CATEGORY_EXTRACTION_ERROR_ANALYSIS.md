# Category Extraction Error Analysis

WIP: `CRM-V3-CATEGORY-ARCHITECTURE-DECOMPOSITION-1`

## Primary split

| Failure class | Architecture A | Architecture B |
|--|--|--|
| Language / form / item understanding | Rare (A1_ITEM_EXTRACTION_ERRORS≈0 on scored fails) | Low on holdout; some cal misses tied to empty/weak extract or unmapped goods |
| Commercial vocabulary / abstention | **Dominant** — A2 over-predicts categories on EXPECTED_EMPTY (NEG_FP 12/15 cal) | **Dominant on cal** — B_REGISTRY_MAPPING_ERROR + REGISTRY_VOCABULARY_GAP |

Conclusion: with decomposition, **category failures are mostly commercial mapping/abstention**, not raw Russian comprehension of titles (especially for directs).

## Architecture A attribution counts (calibration)

From experiment aggregates:

- `A1_ITEM_EXTRACTION_ERRORS` ≈ 0 (among attributed misses)
- `A2_CATEGORY_ERRORS` ≈ 20 (mapping + abstention)
- Pattern: A1 often yields DIRECT_GOODS_PURCHASE + goods phrases even when human label is EXPECTED_EMPTY → A2 maps into registry instead of NO_COMMERCIAL_ENTRY

## Architecture B attribution

- Holdout: zero scored extraction/mapping errors under hard metrics
- Calibration: `B_REGISTRY_MAPPING_ERRORS` ≈ 5; `UNMAPPED_GAPS` ≈ 53 phrase-level gaps across run
- Example 23591: model may extract storm-sewer semantics but registry vocabulary lacks a unique term → empty map (miss)

## Monolithic vs decomposed (directs)

| | Monolithic Qwen v6_1 | Arch A | Arch B |
|--|--:|--:|--:|
| Cal DIRECT_MISSED | 2/16 | **0**/16 | 3/16 |

Decomposition **can** eliminate direct misses (A), but not without destroying negative precision unless abstention is fixed.

## Root-cause labels used

A: `A1_PROCUREMENT_FORM_ERROR`, `A1_ITEM_EXTRACTION_ERROR`, `A1_OBJECT_ERROR`, `A2_CATEGORY_MAPPING_ERROR`, `A2_ABSTENTION_ERROR`  
B: `B_EXTRACTION_ERROR`, `B_REGISTRY_MAPPING_ERROR`
