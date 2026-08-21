# MODEL_POSTPROCESSING_PROVENANCE.md

WIP: Phase 8 audit only.

## Authority chain (unchanged)

| Stage | Store | May invent categories? |
|--|--|--|
| MODEL_RAW | `crm_v3_model_inference_runs.raw_model_json` | model only |
| MODEL_VALIDATED | `validated_model_result` | NO — filter/canonicalize only |
| BUSINESS_RULE | `business_rule_result` / scoring / medal | YES but must be attributed BUSINESS |
| CONTEXT_PRIOR | contextual_prior_hypotheses | PYTHON — never labeled MODEL |
| UI | projection layers | PRESENTATION only |

## Validator behavior (empirical Phase 8)

When RAW emits a non-registry `category_code`, validator drops the hypothesis.
It does **not** rewrite to the nearest valid code.
It does **not** set `empty_hypothesis_status` when the list becomes empty.
Result: many SHADOW empties are **validator wipes of invalid codes**, not true model abstention.

## Business after model (corpus)

Phase 8 dump found **0** `procurement_ai_assessments` rows for the traced SHADOW procurements.
Scores/medals/contextual merges were therefore **not** applied on these audit runs.

`MODEL_VALIDATED_MUTATED=NO`

## Python signals visible to model

| Signal | Visible? | Role |
|--|--|--|
| procurement_form_prior | YES | heuristic in prompt text |
| COMMERCIAL_PRODUCT_PRIORS | YES | inside model-input JSON |
| CONTEXTUAL_RESEARCH_PRIORS | YES | inside model-input JSON |
| OKPD priors list | YES | prompt JSON hints |
| title_hints | YES | subcategory exposure + registry compaction |
| DIRECT_CABLE_EXPECTED_RESULT | YES | model-input field |
| document names/text/evidence | NO | only counts |
