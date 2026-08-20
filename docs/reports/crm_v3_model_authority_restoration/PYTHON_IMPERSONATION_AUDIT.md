# PYTHON_IMPERSONATION_AUDIT.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1` / Phase 6B

## Findings (post-fix)

| Mutation | Before 6B | After 6B |
|---|---|---|
| `object_classification` overwrite by `classify_object` | YES | NO — stored as `business_object_classification` |
| Contextual prior hyps merged into model hyps | YES | NO — `contextual_prior_hypotheses` / `business_category_hypotheses` |
| `procurement_form` coercion as model | YES | NO — `business_procurement_form` |
| Scores/medals on model hyp list | YES | NO — applied only to business hyp set |
| Overall confidence from scored opps labeled model | YES | NO — `MODEL_DERIVED` from validated hyps only |

## Empirical RAW evidence (Phase 6A SHADOW)

Across distinct SHADOW procurements: `VALIDATED_WITH_NONEMPTY_HYPS=0`.

Qwen returned **empty** `commercial_category_hypotheses` for the golden/shadow corpus.
Displayed historical categories were therefore **Python/business**, not model.

```
PYTHON_PRIOR_CREATES_MODEL_CATEGORY=NO
OKPD_PRIOR_MUTATES_MODEL_RESULT=NO
TITLE_SIGNAL_MUTATES_MODEL_RESULT=NO
DETERMINISTIC_ROUTER_MUTATES_MODEL_RESULT=NO
UNEXPECTED_PYTHON_MODEL_CATEGORY_ADDITIONS=0
```
