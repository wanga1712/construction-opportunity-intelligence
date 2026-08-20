# Phase 7 — Model Category Zero-Output Diagnosis

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Phase: 7 (SHADOW only)  
Prompt under audit: `v3_category_centric_routing_7b_v5`

## Verdict

**ZERO_OUTPUT_ROOT_CAUSE** = schema-template / pipe-enum copy + contradictory abstention vs object-mode instructions on a 7B model, producing **silent empty** hypotheses (`commercial_category_hypotheses=[]` with `empty_hypothesis_status=null`).

Not caused by empty registry, validator dropping hyps, or primary truncation.

## 1. Persisted Phase 6A SHADOW runs (RAW)

Source: distinct latest `run_kind=SHADOW` rows in `crm_v3_model_inference_runs` (Phase 6A golden window + subsequent SHADOW).

| Metric | Value |
|--------|-------|
| V5_GOLDEN_RUNS (distinct procurements audited) | 68 |
| RAW_CATEGORY_HYP_NONEMPTY | 0 |
| RAW_CATEGORY_HYP_EMPTY | 68 |
| RAW_NONEMPTY_HYPOTHESES | 0 |
| VALIDATED_NONEMPTY_HYPOTHESES | 0 |
| VALIDATOR_DROPPED_VALID_HYPOTHESES | 0 |

### empty_hypothesis_status

| Status | Count |
|--------|-------|
| EMPTY_STATUS_MISSING (null/empty) | 68 |
| EMPTY_STATUS_NO_COMMERCIAL_ENTRY | 0 |
| EMPTY_STATUS_INSUFFICIENT_EVIDENCE | 0 |
| EMPTY_STATUS_REVIEW_REQUIRED | 0 |
| OTHER_EMPTY_STATUS | 0 |

Interpretation: model is **not** deliberately selecting NO_COMMERCIAL_ENTRY; it leaves silent empty (forbidden by prompt text but still emitted).

### procurement_form / object

PROCUREMENT_FORM_DISTRIBUTION (RAW, n=68):

| Value | Count |
|-------|------:|
| MISSING/null | 57 |
| TENDER | 2 |
| OPEN | 2 |
| other garbage / free-text (RESTRUCTURING, ТЕНДЕР, PRIVATE, ELTTP, …) | 7 |

Allowed enums (`DIRECT_GOODS_PURCHASE`, `CONSTRUCTION_WORKS`, …) essentially unused.

- OBJECT_TYPE_NONEMPTY = 53; OBJECT_TYPE_EMPTY = 15 — object classification often present while categories empty → category failure is **isolated**, not total JSON failure.

## 2. Live prompt path

Production / SHADOW default builder:

- **USES_BUILD_V3_PROMPT_FROM_MODEL_INPUT=YES** (live path via `engine.build_prompt_context` → `build_v3_prompt` → `build_v3_prompt_from_model_input` when model input present).
- PROMPT_VERSION on runs: `v3_category_centric_routing_7b_v5`
- MODEL_INPUT_VERSION: `V3_ROUTING_MODEL_INPUT_V3`

Do not assume the generic `build_v3_prompt` title/OKPD-only path is what Phase 6A used; golden path is model-input builder.

## 3. Registry delivery (hard gate)

| Metric | Value |
|--------|-------|
| REGISTRY_EMPTY_PROMPTS | 0 |
| REGISTRY_MISSING_PROMPTS | 0 |
| REGISTRY_ACTIVE_CATEGORY_COUNT_MIN | 8 |
| REGISTRY_ACTIVE_CATEGORY_COUNT_MAX | 8 |

Live ACTIVE codes observed in prompts (exact): lighting, waterproofing, drainage_water_management, computers, flooring, curbstone, cable_support_systems, composite_structures.

**STOP for empty registry = NO.** Prompt redesign is allowed.

## 4. Validator

RAW empty ⇒ validated empty. Validator does not invent categories and did not drop any nonempty RAW hyps.

`VALIDATOR_DROPPED_VALID_HYPOTHESES=0`

## 5. Truncation / format

| Metric | Value |
|--------|-------|
| NUM_PREDICT (v5 config) | 512 |
| TRUNCATED_RUNS (eval_count≥num_predict heuristic) | 0 |
| FORMAT_RETRY_RUNS | 0 |
| EVAL_COUNT median / max | ~206 / ~1003 |
| CATEGORY_FIELD_POSITION_RISK | MEDIUM — schema example places empty `commercial_category_hypotheses:[]` early; 7B copies skeleton |

Do **not** raise NUM_PREDICT as primary fix; truncation not proven.

## 6. Behavioral classification

| Hypothesis | Supported? |
|------------|------------|
| A. Deliberate abstention with explicit empty status | NO (status missing) |
| B. NO_COMMERCIAL_ENTRY everywhere | NO |
| C. Missing field | NO (field present, empty list) |
| D. Different schema / pipe-enum template copy | **YES** |
| E. Truncation / format constraint primary | NO (secondary risk only) |

## 7. Likely causes of global abstention

1. JSON schema example in `build_v3_prompt_from_model_input` shows empty hypotheses + `empty_hypothesis_status:null` + pipe-joined `overall_research_action`.
2. Competing contracts: strong “do not invent without evidence” vs object-mode “must emit contextual hypotheses for roads/construction”.
3. Road negative example in `_CATEGORY_CODE_CONTRACT` hard-codes drainage as “RIGHT” while elsewhere abstention is emphasized — 7B resolves conflict by copying empty template.
4. Silent-empty ban is stated but schema example violates it.

See `PROMPT_CONTRADICTIONS.md`.

## 8. Remediation direction (Phase 7)

- New prompt version `v3_category_centric_routing_7b_v6` (do not overwrite v5).
- Filled POSITIVE / NEGATIVE / OBJECT examples; forbid silent empty; single-value enums; shorter decision order.
- A/B SHADOW on human-labeled calibration corpus; no production mutate.
