# SFT Dataset Readiness (side output — no training)

WIP: `CRM-V3-CATEGORY-ARCHITECTURE-DECOMPOSITION-1`

```text
MODEL_TRAINING_STARTED=NO
```

From frozen reviewed corpora used in this experiment (union calibration∪holdout, n=89):

| Field | Value |
|--|--:|
| EXPERT_REVIEWED_TOTAL | 89 |
| CLEAR_DIRECT_LABELED | 24 |
| CLEAR_NEGATIVE_LABELED | 23 |
| OBJECT_LABELED | 42 |

Category distribution (exact codes + label kinds): lighting 15, computers 5, flooring 2, cable_support_systems 1, drainage_water_management 1, EXPECTED_EMPTY 23, AMBIGUOUS_REVIEW 42.

```text
SFT_MIN_ADDITIONAL_LABELS_NEEDED=111
```

Rationale: a minimal supervised fine-tune for category/abstention typically needs on the order of ≥200 clean, balanced expert labels. Current reviewed set is useful for eval but thin for SFT, skewed toward ambiguous/object cases.

Do **not** train in this WIP. Next step (if any) is operator-approved labeling or taxonomy vocabulary work, not automatic LoRA.
