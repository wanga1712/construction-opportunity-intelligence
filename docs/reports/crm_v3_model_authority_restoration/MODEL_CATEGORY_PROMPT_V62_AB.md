# Phase 7.1 — Prompt A/B/C and Holdout

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Production prompt unchanged: `v3_category_centric_routing_7b_v5`

## Versions

| Role | Version |
|--|--|
| BASE (frozen) | `v3_category_centric_routing_7b_v6_1` |
| Candidate C | `v3_category_centric_routing_7b_v6_2` |
| Balance attempt D | `v3_category_centric_routing_7b_v6_3` (failed — lighting example leakage) |

## Original calibration (65 cases, relabeled)

Source: `phase71_abc_summary.json` + `phase71_v63_cal.json`

| Metric | v5 | v6_1 | v6_2 | v6_3 |
|--|--:|--:|--:|--:|
| CLEAR_DIRECT_EXACT_MATCH | 0 | **14** | 9 | 9 |
| CLEAR_DIRECT_MISSED | 16 | **2** | 7 | 7 |
| CLEAR_NEGATIVE_FALSE_POSITIVE | 0 | 1 | **0** | 8 |
| CLEAR_NEGATIVE_N | 15 | 15 | 15 | 15 |
| OBJECT_NONEMPTY_CONTEXTUAL | 0 | 12 | 4 | 4 |
| INVALID_CATEGORY_CODE | 0 | 0 | 0 | 0 |
| FORMAT_VALID_RATE | 1.0 | 1.0 | 1.0 | 1.0 |
| PRODUCTION_*_MUTATED | 0 | 0 | 0 | 0 |

### Residual original failures under v6_1 (post label fix)

- Misses: 37082 monoblock, 23591 storm-sewer equipment
- FP: 34524 modular building → lighting (27355 fixed under some runs; 34517 relabeled out of CLEAR_NEGATIVE)

### v6_2 tradeoff

- **Fixed** original residual misses (37082, 23591) and drove **CLEAR_NEGATIVE_FALSE_POSITIVE=0**
- **Regressed** other clear directs (lighting/flooring/cable) via over-abstention from bare-road empty object example
- Object nonempty dropped 12→4 (anti-spam improved)

### v6_3 failure mode

Restoring many POS examples with lighting first caused **EXAMPLE_LEAKAGE**: false `lighting` on services/medical/furniture and wrong-code misses on non-lighting directs.

## Holdout (24 cases, frozen before v6_2/v6_3)

`MODEL_CATEGORY_HOLDOUT_CORPUS.json` — disjoint from calibration.

v6_3 holdout (`phase71_v63_holdout.json`):

| Metric | v6_3 |
|--|--:|
| HOLDOUT_DIRECT_MISSED | 5 |
| HOLDOUT_NEGATIVE_FALSE_POSITIVE | 5 |
| HOLDOUT_INVALID_CATEGORY_CODE | 0 |
| HOLDOUT_HALLUCINATED_CATEGORY_CODE | 0 |

Hard holdout gates **FAIL**.

## Object / road safety

v6_2 reduced generic construction category spam vs v6_1 (OBJECT_NONEMPTY 12→4).  
`GENERIC_CONSTRUCTION_CATEGORY_SPAM` for v6_2: **NO** (improved).  
v6_3: lighting spam on unrelated cases — **YES** (reject).

## Confidence notes

v6_1/v6_2 contextual FPs often confidence≈0.4. Correct directs often 0.7–0.8. No thresholding applied.  
v6_3: many wrong `lighting` at ~0.8 (overconfident leakage).

CONFIDENCE_CALIBRATION_NOTES=correct directs mid-high; v6_3 lighting leakage high-confidence; no gating added.

## Hard acceptance

| Gate | Result |
|--|--|
| ORIGINAL CLEAR_DIRECT_MISSED=0 | FAIL (best residual pair not co-satisfied with zero FP without regressing others) |
| ORIGINAL CLEAR_NEGATIVE_FALSE_POSITIVE=0 | v6_2 PASS; v6_1 FAIL(1); v6_3 FAIL |
| HOLDOUT gates | FAIL (v6_3) |
| OBJECT_CLASSIFICATION_REGRESSION | v6_2 form/object nonempty stable/improved vs v6_1 — treated as 0 regression |
| PRODUCTION_PROMPT_STILL_V5 | YES |

**PHASE_7_1=FAIL** — do not cut over.
