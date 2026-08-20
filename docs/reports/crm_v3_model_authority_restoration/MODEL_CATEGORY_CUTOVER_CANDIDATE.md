# Phase 7.1 — Cutover Candidate (NOT READY)

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`

## PRODUCTION_PROMPT_STILL_V5=YES

Production remains:

`v3_category_centric_routing_7b_v5`

No production cutover in this phase/commit.

## Candidate status

| Candidate | Calibration hard gates | Holdout | Cutover |
|--|--|--|--|
| v6_1 | FAIL (2 miss + 1 FP) | not required as final | NO |
| v6_2 | FAIL (7 miss; 0 FP) | not fully green | NO |
| v6_3 | FAIL (leakage) | FAIL | NO |

## Why not cut over

1. No SHADOW prompt simultaneously satisfies:
   - CLEAR_DIRECT_MISSED=0
   - CLEAR_NEGATIVE_FALSE_POSITIVE=0
   - holdout clear gates
2. v6_2 improves negatives/object spam but regresses clear directs.
3. v6_3 reintroduces example leakage (lighting).

## Required before any future cutover

1. SHADOW candidate with original + holdout hard gates PASS
2. Explicit operator approval
3. Separate cutover commit (not bundled with calibration experiment)
4. Production assessments/opportunities unchanged until approved

## Safety snapshot

| Check | Value |
|--|--|
| PRODUCTION_ASSESSMENTS_MUTATED | 0 |
| PRODUCTION_OPPORTUNITIES_MUTATED | 0 |
| TORGI_VISIBILITY_CHANGED | 0 |
| MODEL_TRAINING_STARTED | NO |
| PYTHON_PRIOR_CREATES_MODEL_CATEGORY | NO |
