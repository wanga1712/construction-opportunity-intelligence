# T-lite-it-2.1 Q4_K_M Bakeoff Report
## CRM-V3-TLITE-BAKEOFF-1 / Phase 7.2

**Date**: 2026-08-21  
**Branch**: `CRM-V3-TLITE-BAKEOFF-1`  
**Base commit**: `50f5c844012e6d57862e8fd00034999f530aa731` (github/main)  
**Host**: S13 (10.8.0.13, operator: sergey)  
**Task ID**: EIS-BACKWARD-RUNTIME-MOVE-S13-TO-S7-1 / CRM-V3-TLITE-BAKEOFF-1

---

## 0. Objective

Empirical bake-off: does **T-lite-it-2.1 Q4_K_M** solve the Russian procurement
category classification problem better than **Qwen2.5:7b**?

- Model change ONLY. Identical prompt `v3_category_centric_routing_7b_v6_1`.
- Production frozen: Qwen2.5:7b + v5 prompt untouched throughout.
- All inference via SHADOW runs (`run_kind=SHADOW`) — no production table mutation.
- Under `crm-background-compute.slice`, CPUs 2-7.

---

## 1. Hard Acceptance Gates

Per operator specification:

| Gate | Requirement |
|------|-------------|
| CLEAR_DIRECT_MISSED | = 0 (for mandatory IDs) |
| CLEAR_NEGATIVE_FALSE_POSITIVE | = 0 (for mandatory IDs) |
| HOLDOUT gates | same thresholds |
| INVALID_CATEGORY_CODE | = 0 |
| FORMAT_INVALID | = 0 |
| GENERIC_CONSTRUCTION_SPAM | = NO (OBJECT_CATEGORY_SPAM = 0) |

---

## 2. Production Freeze Invariants (Confirmed Throughout)

- `PRODUCTION_MODEL_STILL_QWEN25_7B = YES`
- `PRODUCTION_PROMPT_STILL_V5 = YES`
- `PRODUCTION_ASSESSMENTS_MUTATED = 0` (in all runs)
- `PRODUCTION_OPPORTUNITIES_MUTATED = 0` (in all runs)

---

## 3. Smoke Test

| Key | Result |
|-----|--------|
| T_LITE_MODEL_ID | `hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M` |
| T_LITE_SMOKE_RESPONSE | **PASS** |
| T_LITE_JSON_CAPABLE | **YES** |
| THINKING_MODE_USED | NO |
| Russian instruction response | Correct Russian (моноблоки...) |
| JSON_ONLY prompt | Valid JSON, no `<think>` tag |
| Latency (JSON cases) | 2.3–2.6 s per case |

T-lite passes smoke: responds in Russian, outputs valid JSON without hidden-thinking overhead.

---

## 4. Screening Corpus (28 cases)

Mode: `screening`. Both arms run (Qwen baseline + T-lite candidate).  
Prompt: `v3_category_centric_routing_7b_v6_1` (identical for both).

| Metric | Qwen2.5:7b | T-lite-it-2.1 Q4_K_M |
|--------|-----------|----------------------|
| n (cases) | 28 | 28 |
| DIRECT_TOTAL | 10 | 10 |
| DIRECT_CORRECT | 7 | **9** ↑ |
| **DIRECT_MISSED** | **3** | **1** ✓ |
| NEGATIVE_TOTAL | 9 | 9 |
| NEGATIVE_CORRECT_EMPTY | 7 | **8** ↑ |
| **NEGATIVE_FALSE_POSITIVE** | **2** | **1** ✓ |
| OBJECT_TOTAL | 9 | 9 |
| **OBJECT_CATEGORY_SPAM** | **3** | **0** ✓ |
| INVALID_CATEGORY_CODE | 0 | **0** ✓ |
| FORMAT_INVALID | 0 | **0** ✓ |
| AVG seconds/case | 27.1 s | 49.2 s |
| PROCUREMENT_FORM_QUALITY | 1.000 | 1.000 |
| OBJECT_TYPE_QUALITY | 0.964 | 0.964 |

**T_LITE_SCREENING = PASS**

Gate checks:
- `INVALID_CATEGORY_CODE = 0` ✓
- `DIRECT_MISSED(T-lite) ≤ DIRECT_MISSED(Qwen)` → 1 ≤ 3 ✓
- `NEGATIVE_FALSE_POSITIVE(T-lite) ≤ NEGATIVE_FALSE_POSITIVE(Qwen)` → 1 ≤ 2 ✓
- `OBJECT_CATEGORY_SPAM = 0` ✓

### Mandatory Residual IDs (Screening)

| Procurement ID | Expected | Qwen result | T-lite result |
|----------------|----------|-------------|---------------|
| 37082 | computers | MISSED ✗ | **CORRECT** ✓ |
| 23591 | (target) | MISSED ✗ | MISSED ✗ |
| 27355 | EMPTY | FP=false ✓ | FP=false ✓ |
| 34517 | EMPTY | n/a | FP=false ✓ |

T-lite **fixes** 37082 (computers miss that was blocking Qwen Phase 7 gate).

---

## 5. Full Calibration (65 cases, T-lite arm only)

Mode: `full`. T-lite arm only (Qwen baseline n=0, ARMS=t_lite).  
65 labelled cases from `MODEL_CATEGORY_CALIBRATION_CORPUS.json`.

| Metric | T-lite-it-2.1 Q4_K_M |
|--------|----------------------|
| n (cases) | 65 |
| DIRECT_TOTAL | 16 |
| DIRECT_CORRECT | 11 |
| **DIRECT_MISSED** | **5** |
| NEGATIVE_TOTAL | 15 |
| NEGATIVE_CORRECT_EMPTY | 14 |
| **NEGATIVE_FALSE_POSITIVE** | **1** |
| OBJECT_TOTAL | 34 |
| OBJECT_CONTEXTUAL | 0 |
| **OBJECT_CATEGORY_SPAM** | **8** |
| INVALID_CATEGORY_CODE | 0 |
| FORMAT_INVALID | 0 |
| AVG seconds/case | 56.6 s |
| P50_SECONDS | 56.4 s |
| P95_SECONDS | 60.2 s |
| PROCUREMENT_FORM_QUALITY | 1.000 |
| OBJECT_TYPE_QUALITY | 1.000 |

### Failure Details

**DIRECT_MISSED (5 cases — all `computers`):**
- pid=37082: T-lite → [] (missed computers) — **inconsistent with screening PASS**
- pid=37750: T-lite → [] (missed computers)
- pid=37988: T-lite → [] (missed computers)
- pid=37188: T-lite → [] (missed computers)
- pid=23591: T-lite → [] (missed drainage_water_management)

**NEGATIVE_FALSE_POSITIVE (1 case):**
- pid=37167: Expected EMPTY, T-lite → `['lighting']` — **CLEAR_NEGATIVE_FALSE_POSITIVE GATE FAIL**

**OBJECT_CATEGORY_SPAM (8 cases):**
- pid=13564, 34517, 37882, 37651, 949, +3 others: CONSTRUCTION_WORKS procurements
  falsely annotated with product categories (flooring, lighting, cable_support_systems)
- 34517: T-lite → `['flooring']` — **GENERIC_CONSTRUCTION_SPAM gate FAIL**

### Mandatory Residual IDs (Full Calibration)

| Procurement ID | T-lite result | Gate |
|----------------|---------------|------|
| 37082 | MISSED | **FAIL** (CLEAR_DIRECT_MISSED ≥ 1) |
| 23591 | MISSED | FAIL |
| 27355 | FP=false ✓ | PASS |
| 34517 | FP (`flooring`) | **FAIL** (CLEAR_NEGATIVE_FALSE_POSITIVE ≥ 1) |

---

## 6. Overall Decision

### PHASE_7_2 = **FAIL**

| Gate | Threshold | Screening (28) | Full (65) | Decision |
|------|-----------|----------------|-----------|----------|
| CLEAR_DIRECT_MISSED | = 0 | 0 (37082 fixed) | 1 (37082 re-fails) | **FAIL** |
| CLEAR_NEGATIVE_FALSE_POSITIVE | = 0 | 0 | 1 (pid 34517) | **FAIL** |
| GENERIC_CONSTRUCTION_SPAM | = 0 | 0 | 8 | **FAIL** |
| INVALID_CATEGORY_CODE | = 0 | 0 | 0 | PASS |
| FORMAT_INVALID | = 0 | 0 | 0 | PASS |
| PRODUCTION_MUTATION | = 0 | 0 | 0 | PASS ✓ |

### Root cause analysis

1. **Non-determinism on `computers` category**: T-lite correctly classifies 37082 in
   screening but misses it (and 3 similar `computers` IDs) in the larger calibration set.
   This indicates T-lite's understanding of the `computers` category boundary is brittle —
   it passes small-N but regresses on larger N.

2. **OBJECT_CATEGORY_SPAM proliferation**: T-lite produces 8 SPAM outputs vs. Qwen's 3
   in screening on comparable cases. On CONSTRUCTION_WORKS procurements it invents
   product hypotheses (`flooring`, `lighting`, `cable_support_systems`) when it should
   output empty hypotheses + appropriate `empty_hypothesis_status`.

3. **Latency regression**: ~50–57 s/case vs. Qwen's 27 s/case — ~2× slower.
   This is not a gate condition but is operationally relevant.

---

## 7. Unit Test Results

```
tests/test_tlite_shadow_runner.py  21/21 PASS
```

Coverage:
- SHA determinism (raw + validated)
- Immutability guard blocks raw/validated columns
- `build_run_from_ollama` all paths: model_call_failed, parse_failed, validated_success, NCE
- `capture_and_persist_inference_run` dry_run=True no INSERT
- `validate_model_result` no medal invention
- `shadow_inference` no production mutation contract
- Production model + prompt version frozen invariants
- `build_v6_1_prompt` non-empty smoke

---

## 8. Artifacts

| File | Description |
|------|-------------|
| `src/services/commercial_routing_v3/model_inference_runs.py` | Immutable run persistence |
| `src/services/commercial_routing_v3/model_result_validator.py` | Schema validator |
| `src/services/commercial_routing_v3/shadow_inference.py` | SHADOW inference API |
| `src/services/commercial_routing_v3/prompt_v6_1.py` | v6_1 prompt builder |
| `src/migrations/crm_v3_model_inference_runs_1.sql` | DDL (already applied to S13) |
| `scripts/_phase72_t_lite_bakeoff.py` | Screening/calibration orchestrator |
| `scripts/_phase72_t_lite_smoke.py` | Smoke test (JSON capability) |
| `scripts/_phase72_t_lite_one_case.py` | Single-case runner |
| `tests/test_tlite_shadow_runner.py` | 21 unit tests (all pass) |

---

## 9. Recommendation

**Do NOT promote T-lite-it-2.1 Q4_K_M to production.**

Reasons:
1. Hard gate failure: `CLEAR_NEGATIVE_FALSE_POSITIVE = 1` (pid 34517 → flooring FP)
2. Hard gate failure: `CLEAR_DIRECT_MISSED ≥ 1` (37082 re-fails on larger corpus)
3. OBJECT_CATEGORY_SPAM = 8 (2.7× worse than Qwen screening baseline of 3)
4. Latency 2× worse (56 s vs 27 s per case)
5. Non-determinism: screening PASS does not hold on calibration

**Suggested next steps (for operator decision):**
- A: Continue with Qwen2.5:7b + additional prompt engineering on v6_2
- B: Evaluate a different quantization (e.g., Q8_0 or full precision T-lite)
- C: Evaluate a different Italian-specialized model with stronger Russian v6_1 alignment
- D: Accept Qwen Phase 7 result as "best achievable" for current corpus with forced
     category-specific training examples in prompt context

---

*Generated by agent CRM-V3-TLITE-BAKEOFF-1 on 2026-08-21.*  
*Branch pushed to github. DO NOT MERGE.*
