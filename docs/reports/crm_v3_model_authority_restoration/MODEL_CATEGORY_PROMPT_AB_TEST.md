# Phase 7 — Model Category Prompt A/B Test

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Mode: **SHADOW only** (no production assessment/opportunity/visibility mutation)

## Versions

| | |
|--|--|
| PROMPT_VERSION_OLD | `v3_category_centric_routing_7b_v5` |
| PROMPT_VERSION_NEW | `v3_category_centric_routing_7b_v6_1` (iterated from v6 after first A/B) |
| Production default | still **v5** (`prompt.py`) — not cut over |

## Corpus

Source: `MODEL_CATEGORY_CALIBRATION_CORPUS.json`

| Metric | Value |
|--------|------:|
| CALIBRATION_CASES | 65 |
| CLEAR_DIRECT_POSITIVES | 16 (after label corrections) |
| CLEAR_NEGATIVES | 16 |
| OBJECT_CASES | 16 |
| PRIOR11_DIAGNOSTIC | 11 |
| ROAD_CASE_REVIEW | 4 |
| OLD_PYTHON_CATEGORY_IS_GROUND_TRUTH | **NO** |

### Label corrections (not prompt-tuned)

| procurement_id | Was | Became | Reason |
|--|--|--|--|
| 37605 | EXPECTED_EXACT computers | AMBIGUOUS_REVIEW | spare parts/consumables *for* notebooks, not computer purchase |
| 13564 | EXPECTED_EXACT waterproofing | AMBIGUOUS_REVIEW | multi-product bundle (tile + waterproofing + laminate) |

## Run A — Full corpus A/B (v5 vs v6)

`phase7_ab_summary.json` — 63 cases × 2 arms.

| Metric | v5 | v6 |
|--|--:|--:|
| FORMAT_VALID_RATE | 1.0 | 1.0 |
| NONEMPTY_CATEGORY_RATE | 0.0 | 0.587 |
| CLEAR_DIRECT_EXACT_MATCH | 0 | 11 |
| CLEAR_DIRECT_MISSED | 16 | 5 |
| CLEAR_NEGATIVE_CORRECT_EMPTY | 16 | 15 |
| CLEAR_NEGATIVE_FALSE_POSITIVE | 0 | 1 |
| OBJECT_NONEMPTY_CONTEXTUAL | 0 | 14 |
| OBJECT_EMPTY | 16 | 2 |
| INVALID_CATEGORY_CODE | 0 | 0 |
| HALLUCINATED_CATEGORY_CODE | 0 | 0 |
| PRODUCTION_ASSESSMENTS_MUTATED | 0 | 0 |
| PRODUCTION_OPPORTUNITIES_MUTATED | 0 | 0 |

v5 reproduces Phase 6A finding: **global silent empty**.

## Run B — Focused retest after label fixes + v6.1

`phase7_ab_v61_summary.json` — clear directs/negatives only (34 cases × 2).

| Metric | v5 | v6_1 |
|--|--:|--:|
| CLEAR_DIRECT_EXACT_MATCH | 0 | **14** |
| CLEAR_DIRECT_MISSED | 16 | **2** |
| CLEAR_DIRECT_N | 16 | 16 |
| CLEAR_NEGATIVE_CORRECT_EMPTY | 16 | 14 |
| CLEAR_NEGATIVE_FALSE_POSITIVE | 0 | **2** |
| INVALID_CATEGORY_CODE | 0 | 0 |
| PRODUCTION_*_MUTATED | 0 | 0 |

### Remaining v6.1 misses (not relabeled)

| id | title (abbrev) | expect | got |
|--|--|--|--|
| 37082 | Поставка … моноблока | computers | [] silent empty |
| 23591 | Поставка оборудования ливневой канализации | drainage_water_management | [] silent empty |

### Remaining v6.1 false positives

| id | title (abbrev) | got | Notes |
|--|--|--|--|
| 27355 | Поверка газоанализаторов / газовых счетчиков | curbstone | unjustified hallucination |
| 34517 | Текущий ремонт помещений (мед. институт) | lighting | unjustified for CLEAR_NEGATIVE; could be AMBIGUOUS later |

## Acceptance vs hard gates

| Gate | Required | v6_1 | |
|--|--|--|--|
| INVALID_CATEGORY_CODE | 0 | 0 | OK |
| HALLUCINATED_CATEGORY_CODE (registry) | 0 | 0 | OK (codes valid but wrong) |
| CLEAR_DIRECT_MISSED | 0 | 2 | **FAIL** |
| CLEAR_NEGATIVE_FALSE_POSITIVE | 0 or justified | 2 unjustified | **FAIL** |
| FORCED_CATEGORY_EVERYWHERE | NO | NO (rate 0.5 on focus set) | OK |
| PYTHON_PRIOR_CREATES_MODEL_CATEGORY | NO | NO | OK |
| Production mutations | 0 | 0 | OK |

## Road cases (manual review — full v6 arm)

Question: does the model independently propose a commercially plausible research hypothesis?

Observed on object/road titles in full v6 A/B: v5 always empty; v6 often emits 1–2 contextual codes (frequently `drainage_water_management`, sometimes `curbstone` / `lighting` / `composite_structures`) with object_type often `ROAD`.

**Do not treat drainage as required.** Matching old Python priors is diagnostic only (`OLD_PYTHON_CATEGORY_IS_GROUND_TRUTH=NO`). Several road emissions look like residual prior gravity — acceptable only as SHADOW research hypotheses with confirmation_required semantics, not as production truth.

`ROAD_CASES_MANUALLY_REVIEWED=YES` (sample of object/road titles from calibration corpus).

## Prior-11 diagnostic (v5 vs v6 full run)

See supporting extract in git history of A/B JSON; summary: v5 always `[]`; v6 sometimes emits contextual categories. `MATCH_MODEL_TO_PRIOR` is not an acceptance metric.

## Invariants held

- RAW capture / immutable inference runs: YES (new SHADOW run per call)
- RAW_TO_VALIDATED_SEMANTIC_MATCH: YES (validator does not invent categories)
- TORGI_VISIBILITY_CHANGED: 0
- v5 source not overwritten

## Verdict for Phase 7 hard acceptance

**PHASE_7 calibration acceptance = FAIL** on CLEAR_DIRECT_MISSED / CLEAR_NEGATIVE_FALSE_POSITIVE.

**Phase 7 engineering goals met:** zero-output diagnosed; registry gate passed; validator cleared; contradictions documented; new versioned prompt recovers majority of clear directs in SHADOW without production cutover.

Next (explicit request only): further SHADOW prompt iteration / corpus hardening, then production cutover decision.
