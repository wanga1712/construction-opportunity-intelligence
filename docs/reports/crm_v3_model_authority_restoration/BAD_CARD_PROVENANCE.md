# BAD_CARD_PROVENANCE.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`
Phase: 2 — READ-ONLY provenance trace
Date: 2026-08-19

Machine-readable companion: `BAD_CARD_PROVENANCE.json`

---

## Global Findings

| Metric | Value |
|---|---|
| RAW_OLLAMA_JSON_AVAILABLE | **NO** |
| RAW_MODEL_PAYLOAD_IMMUTABLE | **NO** |
| RAW_MODEL_PAYLOAD_HASH_AVAILABLE | **NO** |
| RAW_MODEL_PROVENANCE_INSUFFICIENT | **YES** |
| INVALID_COMPLETE_RESULT_ACCEPTED | **YES** |
| MULTIPLE_MEDAL_AUTHORITIES | **YES** |
| AI_LABEL_CONTAINS_RULE_MEDAL | **YES** |
| PYTHON_PRIOR_CREATES_AI_CATEGORY | **YES** |
| UNASSESSED visible in torgi | **5852 / 6005 (97%)** |

**Raw storage:** `procurement_ai_assessments` has no `raw_*` / `ollama_*` column. Only `normalized_result` (post-Python) is persisted. `crm_v3_inference_attempts` stores telemetry (status, input_hash, failure_class) — not model JSON.

---

## Critical Road SILVER Questions (procurement 840 and peers)

| Question | Answer |
|---|---|
| Did Qwen return `drainage_water_management`? | **Cannot prove.** Raw JSON not stored. Stored hypotheses have `evidence_role=CONTEXTUAL_RESEARCH_PRIOR` → Python `object_mode_routing.py` injection. |
| Did Qwen return `IN_PROFILE`? | **No evidence.** Hardcoded in `runtime_adapter.py:234`. Runner gate (`crm_ai_assessment_runner.py:890-891`) sets IN_PROFILE when Python categories exist. |
| Did Qwen return 100% confidence? | **No.** Hypothesis `confidence=0.0`. UI/DB `confidence=1.0` from Python bug: `float(confidence or 1.0)` treats 0.0 as falsy → 1.0. |
| Did Qwen return SILVER / score 61? | **No.** `normalizer.py` sets `candidate_medal: None`. SILVER/61 from `candidate_scoring.py` (RULE_SCORING). |
| Any field from Python? | **All visible AI fields** on road SILVER cases are Python-derived or Python-defaulted. |

---

## Pipeline Transitions (all bad road cases)

```
SOURCE (reestr_contract_44_fz)
  ↓ projection_writer.py
CRM_PROJECTION → crm_procurements (ai_assessment_status=UNASSESSED initially)
  ↓ crm_ai_assessment_runner.py
MODEL_PROMPT → call_ollama_qwen() [raw in memory only, NOT persisted]
  ↓ engine.route_with_ai()
NORMALIZE → normalizer.py (strips model medals)
  ↓ enrich_object_mode_routing()
OBJECT_MODE_ROUTING → injects _ROAD_CONTEXTUAL_CATS [drainage, waterproofing, curbstone, lighting]
  ↓ apply_candidate_scoring_to_hypotheses()
CANDIDATE_SCORING → SILVER + score 55-68
  ↓ decision_to_normalized_result()
RUNTIME_ADAPTER → hardcodes IN_PROFILE + UNASSESSED route
  ↓ runner business scope gate
RUNNER → IN_PROFILE because proposed_cats non-empty (Python-added)
  ↓ INSERT procurement_ai_assessments
DB → normalized_result only (no raw)
  ↓ persist_category_opportunities()
OPPORTUNITIES → crm_procurement_category_opportunities
  ↓ deadline_pressure / daily reeval
DEADLINE_RULE → SILVER initial → BRONZE effective (ACTIVE_TIMING_DECAY)
  ↓ effective_assessment.py
EFFECTIVE → missing scope → IN_PROFILE default; SUCCESS → ASSESSED
  ↓ tabs.py _load_torgi()
UI → visible in «Идут торги»
```

---

## Case 1: Р-255 «Сибирь» — защитные слои

| Field | Value |
|---|---|
| procurement_id | **840** |
| contract_number | 0351100008926000151 |
| okpd_code | 42.11 |
| ai_assessment_status | COMPLETED |
| model_version | qwen2.5:7b |
| prompt_version | v2a_live_prompt_v2 |

### Field Provenance

| Field | MODEL | After Python | DB Final | UI Final | Tags |
|---|---|---|---|---|---|
| route | ? | UNASSESSED | UNASSESSED | UNASSESSED | PYTHON_HARDCODED (runner L831-835, adapter L235) |
| object_type | ? | unknown | unknown | unknown | PYTHON_HARDCODED |
| procurement_type | ? | UNASSESSED | UNASSESSED | UNASSESSED | PYTHON_HARDCODED |
| business_scope_status | ? | IN_PROFILE | IN_PROFILE | IN_PROFILE | PYTHON_DEFAULTED (adapter L234) + PYTHON_CHANGED (runner gate) |
| category | ? | drainage_water_management, curbstone, waterproofing | same | same | **PYTHON_ADDED** (object_mode_routing, evidence_role=CONTEXTUAL_RESEARCH_PRIOR) |
| confidence | ? | 0.0 per hypothesis | 1.0 aggregate | 100% | PYTHON_CHANGED (0.0→1.0 bug) |
| candidate_medal | stripped None | SILVER | SILVER (nr) / BRONZE (opp effective) | SILVER or BRONZE | RULE_SCORING + DEADLINE_RULE |
| candidate_score | stripped 0 | 61.0 | 61.0 | 61 | RULE_SCORING |

**PYTHON_CREATED_USER_VISIBLE_AI_CATEGORY = YES**

Opportunity row: `initial_medal=SILVER`, `effective_medal=BRONZE`, `effective_reason=ACTIVE_TIMING_DECAY`, `category_confidence=0.0`.

---

## Cases 2–3: А-322 (841), Р-257 (844)

Identical pattern to case 840:
- Route/Object/Procurement = UNASSESSED/unknown/UNASSESSED (Python)
- Scope = IN_PROFILE (Python)
- Categories = drainage_water_management + waterproofing (Python CONTEXTUAL_RESEARCH_PRIOR)
- Medal = SILVER from scoring, effective BRONZE from timing decay

---

## Case 4: Капитальный ремонт моста (10795)

Same pattern. Title mentions bridge repair; Python still injects drainage/waterproofing road priors because OKPD 42.11 + road regex triggers object_mode path.

---

## Case 5: Ремонт дорожного покрытия (27983)

| Field | Value |
|---|---|
| procurement_id | **27983** |
| ai_assessment_status | **UNASSESSED** |
| assessment row | **none** |
| opportunities | **none** |
| visible in torgi | **YES** |

**Visibility cause:** `tabs.py _load_torgi()` SQL:
```sql
WHERE crm_stage='torgi' AND award_status='submission_open' AND end_date >= CURRENT_DATE
```
No AI status check. RAW projected procurement shown as active manager lead.

---

## Case 6: Ремонт автомобильной дороги (13688)

Assessed case — same Python-injected drainage/waterproofing pattern as 840.

---

## Case 7: Спортивная площадка (28111)

UNASSESSED, no assessment, visible in torgi via projection gate only.

---

## Case 8: Ремонт тротуаров (24926)

UNASSESSED, no assessment, visible in torgi via projection gate only.

---

## Case 9: Содержание автомобильных дорог

- **31336** — UNASSESSED, projection-only visibility
- **8003** — COMPLETED with same Python SILVER/drainage pattern as 840

---

## Effective Assessment Logic

### Missing scope → IN_PROFILE

```python
# effective_assessment.py:149
scope_status = (nr.get("business_scope_status") or "IN_PROFILE").upper()
```

Also hardcoded upstream:
```python
# runtime_adapter.py:234
"business_scope_status": "IN_PROFILE",
```

### ASSESSED despite UNASSESSED route/object/procurement

Validation contract (`effective_assessment.py:35-44`):
- Requires only: `business_scope_status` OR `category_opportunities` OR `candidate_level`
- Does NOT require valid route, object, or procurement type
- `procurement_ai_assessments.status=SUCCESS` + non-null normalized_result → `ai_status=ASSESSED`

**Result:** Route=UNASSESSED + Object=unknown + Procurement=UNASSESSED + Scope=IN_PROFILE + Medal=SILVER is accepted as COMPLETED/SUCCESS.

---

## Medal Authority Trace

| Layer | Source | Example (840) |
|---|---|---|
| MODEL_MEDAL | stripped to None by normalizer | null |
| RULE_MEDAL (candidate_scoring) | candidate_initial_medal | SILVER |
| DEADLINE_CAP (timing decay) | current_effective_medal | BRONZE |
| UI aggregate | normalized_result candidate_level | SILVER |
| UI opportunity | candidate_medal column | BRONZE |

**MULTIPLE_MEDAL_AUTHORITIES=YES** — UI can show SILVER (AI section) and BRONZE (effective/opportunity) without explicit labeling of which authority applies.

---

## Code References (Git main, not live runtime)

| Issue | File | Line |
|---|---|---|
| Hardcode IN_PROFILE | `runtime_adapter.py` | 234 |
| Hardcode UNASSESSED route | `runtime_adapter.py` | 235 |
| Hardcode unknown object/route in runner | `crm_ai_assessment_runner.py` | 831-835 |
| IN_PROFILE gate from Python cats | `crm_ai_assessment_runner.py` | 890-891 |
| Confidence 0→1 bug | `crm_ai_assessment_runner.py` | 865 |
| Missing scope default | `effective_assessment.py` | 149 |
| Road prior injection | `object_mode_routing.py` | 64-70, 218-289 |
| Strip model medals | `normalizer.py` | 244-245 |
| Torgi SQL gate (no AI) | `tabs.py _load_torgi()` | crm_stage+award_status+end_date |

---

## PHASE_2 Verdict

```
PHASE_2=PASS
```

All 9 representative cases traced. For assessed road cases: **every user-visible AI field is Python-derived or Python-defaulted**; raw Qwen output cannot be reconstructed. For UNASSESSED cases: **visibility is projection-only**, confirming the visibility gate bug.

**Not committed** — awaiting live-vs-Git reconciliation before commit.
