# PROMPT_CONTRACT_MISMATCH.md

WIP: Phase 6B (updated)

| Field | Prompt returns? | Python creates? | UI as model? | BUG |
|---|---|---|---|---|
| route_profile | NO | YES | NO | NO |
| object_type | YES | business only | YES (from validated) | NO (fixed) |
| object_subtype | YES | business only | YES (from validated) | NO (fixed) |
| project_stage/work_stage | YES | business only | YES (from validated) | NO (fixed) |
| procurement_form/type | YES | coercion → business | YES (model form) | NO (fixed) |
| business_scope_status | NO | YES | NO | NO |
| category hyps | YES | priors → contextual | YES (validated only) | NO (fixed) |
| overall confidence | NO | MODEL_DERIVED | labeled derived | NO (fixed) |
| candidate score/medal | NO | YES | NO (business) | NO |

```
AUTHORITY_MATRIX_SEMANTICALLY_CONSISTENT=YES
PYTHON_AGGREGATE_LABELED_MODEL=NO
```
