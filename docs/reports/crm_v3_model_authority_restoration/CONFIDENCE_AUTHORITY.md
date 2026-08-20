# CONFIDENCE_AUTHORITY.md

WIP: Phase 6B

| Layer | Authority | Notes |
|---|---|---|
| Per-hypothesis `confidence` | `MODEL_VALIDATED` | From validated hyp only |
| Overall aggregate | `MODEL_DERIVED` | `max(model hyp confidence)`; UI «Рассчитано из ответа модели» |
| Business / CandidatePolicy | `BUSINESS_RULE` | Score multiplier — not model |

```
ZERO_CONFIDENCE_PRESERVED=YES
MISSING_CONFIDENCE_NOT_100_PERCENT=YES
AGGREGATED_CONFIDENCE_LABELED_RAW_MODEL=NO
```
