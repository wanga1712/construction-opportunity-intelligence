# FULL_REGISTRY_RESEARCH_PRIORITY_CONTRACT.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1` / **PHASE 9** (SHADOW only)

## Contract

```
FULL ACTIVE REGISTRY
 → MODEL subject_interpretation
 → MODEL commercial_category_candidates (ACTIVE codes only)
 → research_priority HIGH|MEDIUM|LOW
 → document_research_priority (plan, not evidence)
 → later DOCUMENT confirmation (out of scope)
 → BUSINESS scoring (unchanged; not asked of model)
```

Production remains: `qwen2.5:7b` + `v3_category_centric_routing_7b_v5`.

SHADOW prompt: `v3_full_registry_research_priority_7b_v9`

## Registry audit

| Item | Value |
|--|--|
| ACTIVE_CATEGORY_COUNT | 8 |
| Loader | `load_active_commercial_categories` (semantic COMMERCIAL_CATEGORY + ACTIVE/ACTIVE_AI_ONLY) |
| REGISTRY_FIELDS_AVAILABLE | category_code, category_name, description, aliases, positive_scope, negative_scope, lifecycle_state |
| Subcategories in first pass | deferred (`DEFERRED_AFTER_CATEGORY_SELECTION`) |
| FULL_ACTIVE_REGISTRY_VISIBLE_TO_MODEL | YES |
| REGISTRY_CATEGORY_FILTERED_BY_TITLE_HINT | NO |
| REGISTRY_CATEGORY_FILTERED_BY_OKPD_PRIOR | NO |
| REGISTRY_PAYLOAD_DATA_DRIVEN | YES |
| ADDING_ACTIVE_CATEGORY_AUTOMATICALLY_CHANGES_MODEL_REGISTRY | YES (DB ACTIVE row → payload) |
| PROMPT_SOURCE_CHANGE_REQUIRED_FOR_NEW_CATEGORY | NO |
| CATEGORY_DISCOVERABILITY_REQUIRES_STATIC_HINT | NO |
| `_CAT_HINTS` role | legacy v5 subcategory optimization only; v9 does not gate category presence |

## Subject vs taxonomy

`subject_interpretation` is MODEL_VALIDATED (semantic).  
`commercial_category_candidates` / hypotheses are taxonomy selection.  
Validator rejects non-registry codes without inventing replacements; subject is preserved so ITEM vs MAPPING failures stay separable.

## Constrained enum

| Item | Value |
|--|--|
| DYNAMIC_CATEGORY_ENUM_SUPPORTED | NO (Ollama `format=json` only; no dynamic JSON-Schema enum wired) |
| CATEGORY_ENUM_ALLOWS_ABSTENTION | YES (empty candidates + empty_hypothesis_status) |
| INVALID_CODE_GENERATION_STRUCTURALLY_PREVENTABLE | NO (prompt allow-list + validator filter only) |

## Object / research semantics

- Object candidates: `candidate_role=RESEARCH_CANDIDATE`, `confirmation_required=true`, `evidence_role=CONTEXTUAL_RESEARCH_CANDIDATE`
- OBJECT_CATEGORY_REQUIRED=NO
- Medal/score not requested from model
- Document content still not sent to routing

## Production safety

| Guard | Value |
|--|--|
| PRODUCTION_MODEL_CHANGED | NO |
| PRODUCTION_PROMPT_CHANGED | NO |
| PRODUCTION_ASSESSMENTS_MUTATED | 0 |
| PRODUCTION_OPPORTUNITIES_MUTATED | 0 |
| MODEL_VALIDATED_MUTATED | NO |
| PYTHON_PRIOR_CREATES_MODEL_CATEGORY | NO |
