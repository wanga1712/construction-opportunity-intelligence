# MODEL_AUTHORITY_MATRIX.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Phase: 6–7 — MODEL RAW immutability & Authority separation

## Intended field authority matrix (user-visible)

Conventions:
- `MODEL` = Qwen/Ollama is explicitly prompted to output this field (via the V3 prompt contract).
- `BUSINESS_RULE` = deterministic / scoring / routing / timing derived in Python (CandidatePolicy, timing, visibility, priors, fallbacks, etc.).
- `EXPERT` = human annotation workflow.
- `SOURCE` = persisted source-data from CRM/tender entities.
- `DERIVED_UI` = only reformatting/renaming for display.

| User-visible field | Intended authority | Qwen explicitly asked? | Python creates? | Notes |
|---|---|---|---|---|
| `route_profile` | `BUSINESS_RULE` | NO | YES | Derived from prefilter / routing lane logic. |
| `object_type` | `MODEL` | YES | YES (currently overwrites) | Prompt contract requests `object_classification.object_type`, but current runtime may replace it deterministically. |
| `object_subtype` | `MODEL` | YES | YES (currently overwrites) | Same as above: `object_classification.object_subtype`. |
| `project_stage` | `MODEL` | YES | YES (currently overwrites) | Prompt contract requests `object_classification.work_stage` (mapped to UI “project_stage”). |
| `procurement_type` | `MODEL` | YES (via `procurement_form`) | YES | Model is asked for `procurement_form`; UI maps it to `procurement_type`. |
| `business_scope_status` | `BUSINESS_RULE` | NO | YES | Canonicalized by `business_scope.py` / runtime gate; fail-closed and NEVER inferred from categories. |
| `category` | `MODEL` | YES | YES (normalized → stored) | Comes from `commercial_category_hypotheses[*].commercial_category_code`. |
| `subcategory` | `MODEL` | YES (optional) | YES | From `commercial_subcategory_code` (may be null/omitted). |
| `opportunity_track` | `MODEL` | YES | YES (normalized → stored) | From `opportunity_track`. |
| `category_confidence` | `MODEL` | YES | YES | From model per-hypothesis `confidence` (0.0–1.0). |
| `candidate_score` | `BUSINESS_RULE` | NO | YES | Computed by CandidatePolicy / timing rules. |
| `candidate_medal` | `BUSINESS_RULE` | NO | YES | Computed from CandidatePolicy scoring outputs. |
| `deadline/window cap` | `BUSINESS_RULE` | NO | YES | Derived from timing window & execution clock logic. |
| `effective/final medal` | `BUSINESS_RULE` | NO | YES | Final displayed medal from effective assessment & overrides. |
| `overall confidence` | `MODEL` | YES (implicitly) | YES | Derived from model hypothesis confidences (runner computes aggregation). |
| `reason/evidence` | `MODEL` (per-hypothesis) + `BUSINESS_RULE` (pipeline reasons) | YES (per-hypothesis) | YES | Must be separated by provenance; do not collapse to “AI category = …”. |

## Required flags

MODEL_FIELDS_EXPLICITLY_DEFINED=YES  
BUSINESS_RULE_FIELDS_EXPLICITLY_DEFINED=YES  
NO_AMBIGUOUS_USER_VISIBLE_FIELDS=YES

