# PROMPT_CONTRACT_MISMATCH.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Phase: 6–7 — MODEL RAW immutability & Authority separation

This document tracks which user-visible fields are (a) requested from Qwen by the V3 prompt contract and (b) actually created by Python and shown by UI.

## Prompt contract (V3) — fields requested from Qwen

From `src/services/commercial_routing_v3/prompt.py`, the model is asked to emit at least:

`source_contour`, `procurement_form`, `analysis_modes`,  
`object_context`, `material_signals`, `work_methods`, `application_areas`, `brands`,  
`commercial_category_hypotheses[]` (including `category_code`, `subcategory_code`, `opportunity_track`, `confidence` + per-hypothesis reason fields),  
`empty_hypothesis_status`, `preferred_opportunity_track`, `empty_hypothesis_reason_codes`,  
`discovery_required`, `overall_research_action`,  
and in object-mode: `object_classification` + `document_research_priority[]`.

## Mismatch table (user-visible fields)

| Field | Prompt returns it? | Python creates it? | UI labels it as “model result”? | BUG=YES/NO |
|---|---|---|---|---|
| `route_profile` | NO | YES | NO (shown as routing / effective scope) | NO |
| `object_type` | YES (`object_classification.object_type`) | YES (may overwrite deterministic object classification) | NO (hidden in model block) | YES |
| `object_subtype` | YES (`object_classification.object_subtype`) | YES (may overwrite deterministic object classification) | NO (hidden in model block) | YES |
| `project_stage` | YES (`object_classification.work_stage`) | YES (may overwrite deterministic work stage) | NO (hidden in model block) | YES |
| `procurement_type` | YES (via `procurement_form`) | YES | NO (model block shows `procurement_form` not `procurement_type`) | YES |
| `business_scope_status` | NO | YES | NO (scope is treated as business gate) | NO |
| `category` | YES (`commercial_category_hypotheses[].commercial_category_code` mapped) | YES (stored + routed) | YES | NO |
| `subcategory` | YES (optional) | YES (nullable) | YES | NO |
| `opportunity_track` | YES | YES | YES | NO |
| `category_confidence` | YES (per hypothesis `confidence`) | YES (normalized → stored) | YES | NO |
| `candidate_score` | NO | YES | NO (hidden from model block after UI change) | NO |
| `candidate_medal` | NO | YES | NO (hidden from model block after UI change) | NO |
| `deadline/window cap` | NO | YES | N/A (business section) | NO |
| `effective/final medal` | NO | YES | N/A | NO |
| `overall confidence` | NO (implicitly aggregated) | YES | YES (shown as model confidence) | YES (aggregation is not a direct model field) |
| `reason/evidence` | PARTIAL (reason codes may be per hypothesis) | YES | PARTIAL (model block shows per-hypothesis confidence only; business reasons are separate elsewhere) | YES |

