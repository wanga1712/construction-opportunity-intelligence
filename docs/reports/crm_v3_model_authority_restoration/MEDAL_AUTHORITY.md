# MEDAL_AUTHORITY.md

WIP: Phase 6B

| Field | Authority | UI label |
|---|---|---|
| `business_candidate_medal` / `candidate_level` | `BUSINESS_RULE` | Базовая бизнес-медаль |
| `business_candidate_score` | `BUSINESS_RULE` | Бизнес-оценка (score) |
| `effective_medal` | `BUSINESS_RULE` | Текущая медаль (timing/window) |

Never shown inside MODEL section.

```
PYTHON_SCORE_LABELED_AS_MODEL=NO
PYTHON_MEDAL_LABELED_AS_MODEL=NO
CONFLICTING_MEDAL_LABELS_VISIBLE=0  (base vs effective labeled separately when differ)
```
