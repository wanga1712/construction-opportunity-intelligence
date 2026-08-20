# BUSINESS_SCOPE_AUTHORITY.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Phase: 5 — Business scope authority (fail closed)

OPERATING_RULES_MATCH_REAL_SSH_CONFIG=YES

## Contract

| Field | Value |
|---|---|
| Allowed states | `IN_PROFILE`, `OUT_OF_PROFILE`, `UNKNOWN` (existing; not a new enum) |
| MISSING_SCOPE_DEFAULTS_TO_IN_PROFILE | NO |
| RUNTIME_ADAPTER_HARDCODES_IN_PROFILE | NO |
| RUNNER_HARDCODES_IN_PROFILE | NO |
| EFFECTIVE_SCOPE_FAILS_CLOSED | YES |
| BUSINESS_SCOPE_REQUIRED_FOR_ASSESSED | NO |
| UNKNOWN_SCOPE_NEVER_IMPLICITLY_IN_PROFILE | YES |

**RATIONALE:** V3 prompt does not ask Qwen for `business_scope_status`. Requiring it for ASSESSED would collapse every current V3 result to INCOMPLETE. Assessments stay ASSESSED when other schema keys are valid; relevance is UNKNOWN when scope is missing/invalid; torgi publication requires stored explicit `IN_PROFILE` or `OUT_OF_PROFILE`.

## Writers

| FILE | FUNCTION | INPUT | OUTPUT | DEFAULT/FALLBACK | PROVENANCE |
|---|---|---|---|---|---|
| `business_scope.py` | `canonicalize_business_scope` | raw | canonical scope | UNKNOWN | authority |
| `runtime_adapter.py` | `decision_to_normalized_result` | decision | `business_scope_status` | UNKNOWN | no model field |
| `crm_ai_assessment_runner.py` | BUSINESS SCOPE GATE | `ai_res`, route | `business_scope_status` | UNKNOWN; EXCLUDED→OUT_OF_PROFILE | not from categories |
| `effective_assessment.py` | `_compute_effective_assessment` | `normalized_result` | `business_relevance` | UNKNOWN | stored JSON |
| `candidate_policy.py` | `calculate` | arg | scoring gate | default UNKNOWN | caller |
| `card_tabs_medals.py` | manual override | operator | `business_relevance` | none | expert |

SCOPE_WRITER_COUNT=6  
SCOPE_DEFAULT_IN_PROFILE_LOCATIONS_BEFORE=4  
SCOPE_DEFAULT_IN_PROFILE_LOCATIONS_AFTER=0

Not changed: `object_mode_routing.py`, `engine.py`, `normalizer.py`, `projection_writer.py`.

## Before / after

MISSING_SCOPE_BECOMES_IN_PROFILE_BEFORE=YES  
MISSING_SCOPE_DEFAULTS_TO_IN_PROFILE=NO (after)

## Golden replay

GOLDEN_SNAPSHOT_SHA256 metadata `e959ed6dd6a89d1e6adf2fc305e8ae6c12e01370957151489dbbcddb987f3d4c`  
PYTHON_HARDCODED_SCOPE_CASES_IN_PROFILE_AFTER=0

## Live dry-run (no writes)

| Metric | Value |
|---|---|
| TORGI_VISIBLE_BEFORE_PHASE5 | 49 |
| TORGI_VISIBLE_AFTER_SCOPE_FIX (historical rows) | 49 |
| CURRENT_SCOPE_IN_PROFILE | 49 |
| CURRENT_SCOPE_OUT_OF_PROFILE | 0 |
| CURRENT_SCOPE_UNKNOWN | 0 |
| WOULD_REMAIN_VISIBLE | 49 |
| WOULD_HIDE_SCOPE_INVALID | 0 |
| GOOD_CARDS_WOULD_REMAIN | YES (sample 20 remain includes golden open IDs) |
| GOOD_CARDS_WOULD_HIDE | 0 |

## Historical contamination (no bulk UPDATE)

| Metric | Value |
|---|---|
| CURRENT_ASSESSED_TOTAL | 3693 |
| ASSESSED_SCOPE_IN_PROFILE | 2406 |
| ASSESSED_SCOPE_OUT_OF_PROFILE | 1249 |
| ASSESSED_SCOPE_UNKNOWN | 38 |
| PROVABLE_MODEL_SCOPE | 0 (RAW Qwen not persisted) |
| UNPROVABLE_SCOPE_PROVENANCE | 2406 IN_PROFILE + 1249 OUT_OF_PROFILE stored without raw model proof |
| NEEDS_REASSESSMENT_SCOPE | 2406 (stored IN_PROFILE cannot be proven as model) |
| EXISTING_BAD_SCOPE_ROWS | 2406 |

## Deploy

| Metric | Value |
|---|---|
| CRM_RUNTIME_BACKUP_CREATED | YES |
| CRM_RUNTIME_BACKUP_ALIAS | `/opt/CRM_Streamlit/backups/phase5_scope_20260820T053125Z` |
| CANONICAL_RUNTIME_HASH_MATCH | YES |
| CRM_V3_DEPLOYED | YES |
| Restarts | `crm-streamlit.service` (active); `crm-ai-assessment-runner.service` is Type=oneshot (inactive after run; timer still active) |

NEW_MISSING_SCOPE_RESULT=UNKNOWN_OR_INCOMPLETE  
NEW_MISSING_SCOPE_IN_PROFILE=0 (live import of deployed `resolve_pipeline_scope`: missing/cats/invalid → UNKNOWN; explicit IN/OUT preserved)

No bulk reassessment. No Ollama/PostgreSQL/document/S7 restarts.

## Git

PHASE5_COMMIT=e8a9a74aac98070cad660140c9e9358b3ecd040d  
PHASE5_FINAL_COMMIT=43b0bc122086d45db0b4ba22f2df20f3b9e44255

```
PHASE_5=PASS
```
