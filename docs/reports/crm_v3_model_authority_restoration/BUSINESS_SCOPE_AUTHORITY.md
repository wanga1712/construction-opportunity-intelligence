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

**RATIONALE (ASSESSED vs INCOMPLETE):** V3 prompt/schema do not require the model to emit `business_scope_status`. Making missing scope INCOMPLETE would mark every current V3 assessment incomplete because Qwen is not asked for this field. Completeness stays ASSESSED when other schema keys are valid; relevance stays UNKNOWN; torgi publication fails closed unless stored scope is explicit `IN_PROFILE` or `OUT_OF_PROFILE`.

## Writers (after fix)

| FILE | FUNCTION | INPUT | OUTPUT | DEFAULT/FALLBACK | PROVENANCE |
|---|---|---|---|---|---|
| `business_scope.py` | `canonicalize_business_scope` | raw | canonical scope | UNKNOWN | authority |
| `runtime_adapter.py` | `decision_to_normalized_result` | decision | `business_scope_status` | UNKNOWN | no model field |
| `crm_ai_assessment_runner.py` | BUSINESS SCOPE GATE | `ai_res`, route | `business_scope_status` | UNKNOWN; EXCLUDED→OUT_OF_PROFILE | not from categories |
| `effective_assessment.py` | `_compute_effective_assessment` | `normalized_result` | `business_relevance` | UNKNOWN | stored JSON |
| `candidate_policy.py` | `calculate` | arg | scoring gate | default UNKNOWN (OUT_OF_PROFILE still skips) | caller |
| `card_tabs_medals.py` | manual override | operator | `business_relevance` | none | expert |

SCOPE_WRITER_COUNT=6  
SCOPE_DEFAULT_IN_PROFILE_LOCATIONS_BEFORE=4 (`runtime_adapter` hardcode, `effective_assessment` `or IN_PROFILE`, runner `proposed_cats→IN_PROFILE`, `CandidatePolicy` default)  
SCOPE_DEFAULT_IN_PROFILE_LOCATIONS_AFTER=0

**Not changed:** `object_mode_routing.py`, `engine.py`, `normalizer.py`, `projection_writer.py` (no scope assignment).

## Before / after fixtures

MISSING_SCOPE_BECOMES_IN_PROFILE_BEFORE=YES (`nr.get(...) or "IN_PROFILE"` and adapter `"IN_PROFILE"`).

After: missing/null/empty/invalid → UNKNOWN; explicit IN/OUT preserved.

## Golden replay

Snapshot metadata SHA256 `e959ed6dd6a89d1e6adf2fc305e8ae6c12e01370957151489dbbcddb987f3d4c` unchanged.  
PYTHON_HARDCODED_SCOPE_CASES_IN_PROFILE_AFTER=0 (replay via provenance).

## Live / deploy

Filled in Phase 5 live continuation.
