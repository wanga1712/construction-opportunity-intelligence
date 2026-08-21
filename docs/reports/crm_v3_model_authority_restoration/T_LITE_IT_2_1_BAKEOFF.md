# T-lite-it-2.1 SHADOW bake-off (Phase 7.2)

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Branch pushed with resource + evaluation commits.

```text
PHASE_7_2=FAIL
CATEGORY_MODEL_DECISION=TLITE_NOT_SUFFICIENT
MODEL_CANDIDATE_READY=NO
T_LITE_CLOSE_CANDIDATE=NO
PRODUCTION_CUTOVER=NO
FINE_TUNE=NO
```

## Resource preflight

| Check | Result |
|--|--|
| RESOURCE_GUARANTEE_COMMIT | `0d1ba41951d3a5fa21ed2f85c809b7cb85071139` |
| In canonical WIP history / origin | **YES** |
| Runtime slice AllowedCPUs | `2-7` |
| Runtime CRM MemorySwapMax | `0` |
| Wrapper `scripts/run_background_compute.sh` | tracked + present on S13 |
| RESOURCE_RUNTIME_GIT_MATCH | **YES** |

Heavy arms executed as systemd units in `crm-background-compute.slice` (same policy as the wrapper).

## Worktree classification (at close)

- **TLITE_EXPERIMENT (committed):** bakeoff/smoke/launch scripts, `ai_client` chat+`think:false` experiment path, shadow overrides, result JSONs, this report family.
- **RESOURCE_WIP (committed earlier):** slice/drop-ins, memory/CPU policy, UI contention helpers.
- **UNRELATED (left dirty, not committed):** phase4–6b ops scripts, arch-decomposition experiment stubs, `.hygiene/`, minor diagnosis touch.

No destructive reset/clean.

## Production freeze

```text
PRODUCTION_MODEL_STILL_QWEN25_7B=YES
PRODUCTION_PROMPT_STILL_V5=YES   # prompt.py PROMPT_VERSION=v3_category_centric_routing_7b_v5
PRODUCTION_ASSESSMENTS_MUTATED=0
PRODUCTION_OPPORTUNITIES_MUTATED=0
MODEL_TRAINING_STARTED=NO
```

Fair comparison prompt (SHADOW only): frozen `v3_category_centric_routing_7b_v6_1` identical for both arms.

Decoding: T-lite uses `/api/chat` + `format=json` + `think:false` (Qwen3 GGUF); Qwen keeps production `/api/generate` + `format=json`.

## Candidate

```text
T_LITE_MODEL_ID=hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M
T_LITE_QUANTIZATION=Q4_K_M
T_LITE_MODEL_SIZE≈5.0 GB
OLLAMA_VERSION=0.32.1
```

## Smoke / screening

```text
T_LITE_SMOKE=PASS
T_LITE_JSON_CAPABLE=YES
T_LITE_SCREENING_CASES=28
T_LITE_SCREENING=PASS
```

Screening (28 = holdout 24 + residuals 37082/23591/27355/34517): T-lite ≤ Qwen on DIRECT_MISSED / NEG_FP and OBJECT_SPAM=0 → advanced.

### Holdout-only (24, derived from screening)

| Metric | Qwen v6_1 | T-lite |
|--|--:|--:|
| DIRECT_MISSED | 1 | **0** |
| NEGATIVE_FALSE_POSITIVE | 2 | **1** |
| OBJECT_CATEGORY_SPAM | 3 | **0** |
| INVALID / FORMAT | 0 / 0 | 0 / 0 |

Holdout alone looks strong for T-lite but **hard gate requires NEG_FP=0** → already fails perfect acceptance.

## Full calibration (65)

| Metric | Qwen v6_1 | T-lite |
|--|--:|--:|
| CLEAR_DIRECT_MISSED | **2** | 5 |
| NEGATIVE_FALSE_POSITIVE | **0** | 1 |
| OBJECT_CATEGORY_SPAM | 14 | **8** |
| INVALID / FORMAT | 0 / 0 | 0 / 0 |
| AVG / P95 seconds | 28.0 / 30.2 | 56.6 / 60.2 |

```text
T_LITE_CLEAR_DIRECT_MISSED=5
T_LITE_NEGATIVE_FALSE_POSITIVE=1
T_LITE_INVALID_CATEGORY_CODE=0
T_LITE_FORMAT_INVALID=0
T_LITE_GENERIC_CONSTRUCTION_CATEGORY_SPAM=YES (8 object spam cases)
```

Full corpus reverses the screening story: Qwen better on directs/negatives.

## Known residuals (screening dual-arm)

| ID | Expected | Qwen v6_1 | T-lite v6_1 |
|--|--|--|--|
| 37082 | computers | empty (miss) | **computers** OK |
| 23591 | drainage_water_management | lighting (miss) | empty (miss) |
| 27355 | empty | empty OK | empty OK |
| 34517 | ambiguous/object | empty | empty (forms differ) |

T-lite understands monoblock (37082) better; does **not** solve 23591.

## Hard acceptance (calibration + holdout)

Required zeros on CLEAR_DIRECT_MISSED / CLEAR_NEG_FP for both corpora: **not met**.

```text
MODEL_CANDIDATE_READY=NO
T_LITE_CLOSE_CANDIDATE=NO
CATEGORY_MODEL_DECISION=TLITE_NOT_SUFFICIENT
```

Does T-lite solve the category problem where Qwen failed? **No** on the frozen full calibration under identical v6_1 prompt.

## Resources / CRM guard

```text
T_LITE_EXECUTION_MODE=systemd-run → crm-background-compute.slice
BACKGROUND_CPU_AFFINITY_CORRECT=YES (AllowedCPUs=2-7)
CRM_UI_RESPONSIVE_DURING_TLITE=YES (HTTP 200 during runs)
CRM_SWAP_DURING_TLITE=0
HEAVY_COMPUTE_OUTSIDE_CONTROLLED_CGROUP=0
```

VRAM peak during loaded T-lite inference historically ~model footprint on GTX 1660 SUPER 6 GiB; host RAM available stayed multi‑GiB; swap not driven into CRM (MemorySwapMax=0).

## Authority contract

```text
PYTHON_PRIOR_CREATES_MODEL_CATEGORY=NO
RAW_TO_VALIDATED_SEMANTIC_MATCH=YES (SHADOW capture via crm_v3_model_inference_runs)
OLD_PYTHON_CATEGORY_IS_GROUND_TRUTH=NO
```

## Artifacts

- `phase72_t_lite_screening.json`
- `phase72_t_lite_full.json`
- `phase72_qwen_full.json`
- `phase72_holdout_derived.json`
- Prior summary: `MODEL_CATEGORY_T_LITE_BAKEOFF.md`

## Commits

```text
RESOURCE_GUARANTEE_COMMIT=0d1ba41951d3a5fa21ed2f85c809b7cb85071139
PHASE72_COMMIT=540bad130e9a571591d8de65d1416b636f636bda
```

## STOP

No production switch, no fine-tune, no prompt retune, no bulk reassessment without a new operator instruction.
