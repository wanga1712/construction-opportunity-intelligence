# Category Architecture Decomposition

WIP: `CRM-V3-CATEGORY-ARCHITECTURE-DECOMPOSITION-1`  
Branch/worktree separate from model-authority restoration. Production unchanged.

```text
CATEGORY_ARCHITECTURE_DECISION=NOT_READY
WIP=FAIL
PRODUCTION_MODEL_STILL_QWEN25_7B=YES
PRODUCTION_PROMPT_STILL_V5=YES
PRODUCTION_ASSESSMENTS_MUTATED=0
PRODUCTION_OPPORTUNITIES_MUTATED=0
```

## Setup

- Architectures: **A** two-pass Qwen (A1 semantic → A2 category); **B** extract + deterministic registry map
- Corpora: frozen Phase 7 calibration (65) + Phase 7.1 holdout (24); union n=89 (no relabel)
- Execution: `crm-arch-decomposition.service` under `crm-background-compute.slice`
- Immutable SHADOW runs in `crm_v3_model_inference_runs` (A1/A2 linked per case)

## Metrics

### Architecture A (2 model calls/case)

| Corpus | DIRECT_MISSED | NEG_FP | OBJECT_SPAM | AVG_s |
|--|--:|--:|--:|--:|
| Calibration | **0**/16 | **12**/15 | 8/34 | 13.6 |
| Holdout | **0**/8 | **4**/8 | 1/8 | 13.6 |

A1 item extraction errors (scored): 0. A2 category/abstention errors dominate FP.

### Architecture B (1 model call + business map)

| Corpus | DIRECT_MISSED | NEG_FP | OBJECT_SPAM | AVG_s | vocab gaps |
|--|--:|--:|--:|--:|--:|
| Calibration | 3/16 | 2/15 | 1/34 | 4.6 | 53 |
| Holdout | **0**/8 | **0**/8 | **0**/8 | 4.7 | 21 |

Holdout meets hard zeros for B; **calibration does not** → overall hard acceptance fails.

## Critical cases

| ID | Expected | A2 | B mapped | Notes |
|--|--|--|--|--|
| 37082 | computers | computers | computers | both OK |
| 23591 | drainage… | drainage_water_management | [] | A OK; B vocab gap |
| 27355 | empty | [] | [] | both OK |
| 34517 | ambiguous | [] | [] | both empty OK |

## Decision rationale

- **A** solves the Qwen direct-miss problem (0 misses) but fails abstention (many false positives on negatives) and still has object spam → not ready.
- **B** has truthful provenance (`BUSINESS_RULE_FROM_MODEL_EXTRACTION`) and perfect holdout hard metrics, but calibration still has 3 direct misses + 2 FP + vocabulary gaps → not ready.
- Preferring “pure AI” is rejected: neither architecture clears **both** frozen corpora.

```text
CATEGORY_ARCHITECTURE_DECISION=NOT_READY
```

## Guardrails

```text
HEAVY_COMPUTE_OUTSIDE_CONTROLLED_CGROUP=0
CRM_UI_RESPONSIVE=YES
CRM_SWAP=0
FIELD_PROVENANCE_AVAILABLE=YES
BUSINESS_MAPPING_IMPERSONATES_MODEL=NO
FORCED_OBJECT_CATEGORY=NO
MODEL_TRAINING_STARTED=NO
```

## Artifacts

- `arch_decomposition_summary.json`
- `CATEGORY_EXTRACTION_ERROR_ANALYSIS.md`
- `CATEGORY_REGISTRY_MAPPING_AUDIT.md`
- `SFT_DATASET_READINESS.md`
