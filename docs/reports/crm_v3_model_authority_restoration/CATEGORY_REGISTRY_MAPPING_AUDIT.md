# Category Registry Mapping Audit

WIP: `CRM-V3-CATEGORY-ARCHITECTURE-DECOMPOSITION-1`

## Mapper design

Module: `crm_streamlit/src/services/commercial_routing_v3/registry_extract_mapper.py`

```text
HARDCODED_PRODUCT_SWITCHES=NO
BUSINESS_MAPPING_IMPERSONATES_MODEL=NO
PROVENANCE=BUSINESS_RULE_FROM_MODEL_EXTRACTION
```

Vocabulary sources (live ACTIVE taxonomy only):

- `category_code` / `category_name` / description
- `aliases`, `positive_signals` when columns exist
- subcategory codes/names
- subcategory search/alias/brand terms when table present

Matching: normalized substring uniqueness — ambiguous multi-code hits become gaps (no invent).

## Live index size (S13 run)

```text
VOCAB_TERM_COUNT=275
REGISTRY_VOCABULARY_GAP=YES
```

Observed during Architecture B: dozens of unmapped explicit goods phrases (53 gap events on calibration arm). Example class: morphological variants (`моноблока` vs indexed `моноблок`) and domain phrases without taxonomy aliases (storm sewer / drainage wording).

## Recommendation

Prefer **canonical taxonomy vocabulary enrichment** (aliases, positive signals, morphological forms) over hidden Python exceptions.

Do **not** add `if "моноблок" → computers` in mapper code; if needed, add alias on `computers` in registry.

```text
REGISTRY_VOCABULARY_GAP=YES
```
