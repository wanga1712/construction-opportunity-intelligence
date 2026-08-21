# PHASE9_CATEGORY_EVALUATION.md

WIP: Phase 9 SHADOW evaluation (`phase9_full_registry_results.json`)

## Focus retests

### 37082 (was CATEGORY_MAPPING_ERROR)

| Metric | Value |
|--|--|
| 37082_SUBJECT_INTERPRETATION_CORRECT | YES (computer / monoblock family) |
| 37082_CATEGORY | computers |
| 37082_INVALID_CODE | NO |
| 37082_CATEGORY_MAPPING_ERROR_FIXED | YES |

### 23591 (was ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR)

| Metric | Value |
|--|--|
| 23591_SUBJECT_INTERPRETATION | storm-drainage equipment family (GOODS) |
| 23591_ITEM_UNDERSTANDING_CORRECT | YES |
| 23591_CATEGORY | drainage_water_management |
| 23591_CATEGORY_SELECTION_VALID | YES |
| 23591_ROOT_FAILURE_FIXED | YES |

No special-case hardcoding for ливнев*/моноблок.

### 27355 / 34517 (object overreach)

| Metric | Value |
|--|--|
| 27355_OBJECT_PRIOR_OVERREACH_FIXED | YES (SERVICE; empty candidates; was curbstone/ROAD) |
| 34517_OBJECT_PRIOR_OVERREACH_FIXED | YES for validated empty (RAW briefly invented `renovation`, validator wiped; no lighting FP) |

## Corpora

| Gate | Calibration | Holdout |
|--|--|--|
| DIRECT_MISSED | 1 / 16 | 0 / 8 |
| NEGATIVE_FALSE_POSITIVE | 5 / 15 | 0 / 8 |
| INVALID_CATEGORY_CODE (RAW) | 19 | 12 |
| FORMAT_INVALID | 0 | 0 |
| OBJECT_RESEARCH_CANDIDATE_PRESENTED_AS_CONFIRMED (heuristic sum) | 13 | 1 |

Holdout clean on hard DIRECT/NEG gates. Calibration still has residual negative FP and RAW invented codes (validator empties them).
