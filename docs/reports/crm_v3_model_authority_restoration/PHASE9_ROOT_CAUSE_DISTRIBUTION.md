# PHASE9_ROOT_CAUSE_DISTRIBUTION.md

WIP: Phase 9 — root causes kept separate from surface INVALID_CODE.

## Calibration (n=65) primary roots

| PRIMARY_ROOT_CAUSE | N |
|--|--|
| NO_ERROR | 56 |
| OBJECT_PRIOR_OVERREACH | 8 |
| ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR | 1 |

## Holdout (n=24) primary roots

| PRIMARY_ROOT_CAUSE | N |
|--|--|
| NO_ERROR | 23 |
| OBJECT_PRIOR_OVERREACH | 1 |

## Surface (not collapsed into root)

| Surface | Cal | Hold |
|--|--|--|
| INVALID_REGISTRY_CODE_GENERATION (RAW codes not in ACTIVE) | 19 | 12 |
| ABSTENTION_ERROR (as primary) | 0 | 0 |
| CATEGORY_MAPPING_ERROR (as primary) | 0 | 0 |

Many negative cases still emit invented out-of-registry product names (`medical_equipment`, OKPD strings, etc.); validator removes them → commercially empty, but INVALID_CATEGORY_CODE surface remains >0.

## Focus mapping to Phase 8 classes

| Case | Phase 8 root | Phase 9 root |
|--|--|--|
| 37082 | CATEGORY_MAPPING_ERROR | NO_ERROR |
| 23591 | ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR | NO_ERROR |
| 27355 | OBJECT_PRIOR_OVERREACH | NO_ERROR |
| 34517 | OBJECT_PRIOR_OVERREACH | NO_ERROR (validated) |

Residual distribution for next phase choice: mainly **OBJECT_PRIOR_OVERREACH** + **INVALID_REGISTRY_CODE_GENERATION** surface (structural enum still unavailable).
