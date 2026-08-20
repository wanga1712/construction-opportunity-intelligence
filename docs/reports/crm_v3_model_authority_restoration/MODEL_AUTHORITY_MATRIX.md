# MODEL_AUTHORITY_MATRIX.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Phase: 6B — Semantic namespace separation

## Authority classes

| Class | Meaning |
|---|---|
| `MODEL_VALIDATED` | Value exists in `crm_v3_model_inference_runs.validated_model_result` and originates from Qwen RAW (schema validation only). |
| `MODEL_DERIVED` | Deterministic transform using **only** validated model fields (no source/prior/business inputs). UI: «Рассчитано из ответа модели». |
| `BUSINESS_RULE` | Python routing / scoring / timing / scope. |
| `CONTEXT_PRIOR` | OKPD / title / object_mode contextual prior — never MODEL. |
| `SOURCE_DATA` | Procurement / tender source fields. |
| `EXPERT` | Human annotation. |
| `UI_DERIVED` | Display rename only. |
| `UNKNOWN_LEGACY` | Assessment with `inference_run_id IS NULL` — model provenance unavailable. |

`MODEL` in older docs maps to `MODEL_VALIDATED` only.  
A Python aggregation of model fields is **`MODEL_DERIVED`**, not MODEL.

## Canonical MODEL authority

**Count = 1:** `crm_v3_model_inference_runs.validated_model_result`  
via `procurement_ai_assessments.inference_run_id`.

`procurement_ai_assessments.normalized_result` = **COMPATIBILITY / BUSINESS-ENRICHED**  
→ `NORMALIZED_RESULT_IS_MODEL_AUTHORITY=NO`

## Field matrix (user-visible)

| Field | Authority | Qwen asked? | Notes |
|---|---|---|---|
| `object_type` | `MODEL_VALIDATED` | YES (`object_classification.object_type`) | Python classify_object → `business_object_classification` only. |
| `object_subtype` | `MODEL_VALIDATED` | YES | Same. |
| `project_stage` / `work_stage` | `MODEL_VALIDATED` | YES (`work_stage`) | Same. |
| `procurement_type` / `procurement_form` | `MODEL_VALIDATED` | YES (`procurement_form`) | Form coercion → `business_procurement_form`. |
| `category` / hyp | `MODEL_VALIDATED` | YES | Only `commercial_category_hypotheses` from validated. |
| `subcategory` | `MODEL_VALIDATED` | YES (optional) | |
| `opportunity_track` | `MODEL_VALIDATED` | YES | Business may coerce track on **business** hyps only. |
| `category_confidence` | `MODEL_VALIDATED` | YES | Per-hypothesis. |
| `overall confidence` | `MODEL_DERIVED` | NO | Max of model hyp confidences; UI «Рассчитано из ответа модели». |
| `route_profile` | `BUSINESS_RULE` | NO | Never labeled as model. |
| `business_scope_status` | `BUSINESS_RULE` | NO | Phase 5 contract. |
| `contextual prior category` | `CONTEXT_PRIOR` | NO | `contextual_prior_hypotheses`. |
| `candidate_score` | `BUSINESS_RULE` | NO | UI: бизнес-оценка. |
| `candidate_medal` | `BUSINESS_RULE` | NO | UI: базовая бизнес-медаль. |
| `effective_medal` | `BUSINESS_RULE` | NO | Timing/window; labeled separately when ≠ base. |
| `reason/evidence` | split | YES/NO | Model reasons vs pipeline reasons. |

## Required flags

```
AUTHORITY_MATRIX_SEMANTICALLY_CONSISTENT=YES
PYTHON_AGGREGATE_LABELED_MODEL=NO
MODEL_NAMESPACE_AUTHORITY_COUNT=1
NORMALIZED_RESULT_IS_MODEL_AUTHORITY=NO
```
