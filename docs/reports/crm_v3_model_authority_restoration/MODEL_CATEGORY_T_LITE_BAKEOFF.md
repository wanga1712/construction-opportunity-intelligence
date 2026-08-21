# Phase 7.2 — T-lite-it-2.1 SHADOW bake-off

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Model: `hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M`  
Prompt: frozen `v3_category_centric_routing_7b_v6_1` (identical for both arms)  
Production: **unchanged** (`qwen2.5:7b` + production `v5`)

```text
PHASE_7_2_T_LITE_SCREENING=PASS
PHASE_7_2_T_LITE_FULL=FAIL_FOR_CUTOVER
PRODUCTION_CUTOVER=NO
FINE_TUNE=NO
PRODUCTION_ASSESSMENTS_MUTATED=0
PRODUCTION_OPPORTUNITIES_MUTATED=0
```

## Decoding note

T-lite is Qwen3-family GGUF. Without `think: false` on `/api/chat`, hidden thinking consumes `num_predict` → empty `content`. Experiment path only:

- Qwen baseline: production `/api/generate` + `format=json`
- T-lite: `/api/chat` + `format=json` + `think: false`

## Screening (28 = holdout 24 + residuals)

| Metric | Qwen v6_1 | T-lite |
|--|--:|--:|
| DIRECT_MISSED | 3 | **1** |
| NEGATIVE_FALSE_POSITIVE | 2 | **1** |
| OBJECT_CATEGORY_SPAM | 3 | **0** |
| INVALID / FORMAT | 0 / 0 | 0 / 0 |
| AVG_SECONDS | 27.1 | 49.2 |

`T_LITE_SCREENING=PASS` → advanced to full corpus.

Artifacts: `phase72_t_lite_screening.json`

## Full calibration (65 cases, same scorer)

Both arms run under `crm-background-compute.slice` (`AllowedCPUs=2-7`).

| Metric | Qwen v6_1 | T-lite | Better |
|--|--:|--:|--|
| DIRECT_CORRECT | **14**/16 | 11/16 | Qwen |
| DIRECT_MISSED | **2** | 5 | Qwen |
| NEGATIVE_CORRECT_EMPTY | **15**/15 | 14/15 | Qwen |
| NEGATIVE_FALSE_POSITIVE | **0** | 1 | Qwen |
| OBJECT_CATEGORY_SPAM | 14 | **8** | T-lite |
| INVALID_CATEGORY_CODE | 0 | 0 | = |
| FORMAT_INVALID | 0 | 0 | = |
| AVG_SECONDS | **28.0** | 56.6 | Qwen |

```text
FULL_BEAT_OR_TIE_QWEN=NO
FULL_OBJECT_SPAM_ZERO=NO
RECOMMEND_PRODUCTION_CUTOVER=NO
```

Screening optimism did **not** hold on the full 65-case corpus: T-lite misses more clear directs (esp. computers) and is ~2× slower. Lower object spam vs Qwen is real but insufficient for cutover.

Artifacts: `phase72_t_lite_full.json`, `phase72_qwen_full.json`

## Residuals (full T-lite)

| ID | Expected | T-lite |
|--|--|--|
| 37082 | computers | empty (miss) |
| 23591 | drainage_water_management | empty (miss) |
| 27355 | empty | empty OK |
| 34517 | empty (neg) | flooring (object/spam path) |

## Policy / next

- Keep production on Qwen2.5:7b + `v5`
- Do **not** fine-tune yet unless a new WIP explicitly authorizes it
- Future one-off AI jobs must use background slice (`scripts/run_background_compute.sh`)
