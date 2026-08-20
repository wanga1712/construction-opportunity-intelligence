# Phase 7.1 — Residual Failure Forensics

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Baseline SHADOW: `v3_category_centric_routing_7b_v6_1`  
Candidate: `v3_category_centric_routing_7b_v6_2`

## FOUR_FAILURES_ROOT_CAUSED=YES

Negative FP IDs from Phase 7: **27355**, **34517**.

### 37082 — monoblock (CLEAR_DIRECT miss)

| Field | Value |
|--|--|
| TITLE | Поставка компьютера персонального настольного (моноблока) |
| OKPD | 26.2 — Компьютеры и периферийное оборудование |
| FORM_PRIOR | DIRECT_GOODS_PURCHASE (expected) |
| v6_1 result | hypotheses=[] ; empty_hypothesis_status=null |
| CURRENT_LABEL | EXPECTED_EXACT_CATEGORY=computers |
| LABEL_CORRECT | **YES** |
| PRIMARY_ROOT_CAUSE | **OVER_ABSTENTION** / CATEGORY_MAPPING_MISS |

Nearest successes: other `computers` supply titles (ноутбук/ПК) matched under v6_1. Distinction: title uses **моноблок** which was only weakly covered in v6_1 map list (`ноутбук/ПК`).

### 23591 — storm sewer equipment (CLEAR_DIRECT miss)

| Field | Value |
|--|--|
| TITLE | Поставка оборудования ливневой канализации … |
| OKPD | 22.23.13.194 — tubes/pipes plastic >300mm |
| FORM_PRIOR / notes | Supply of equipment — DIRECT_GOODS plausible |
| v6_1 result | hypotheses=[] ; silent empty |
| CURRENT_LABEL | EXPECTED_EXACT_CATEGORY=drainage_water_management |
| LABEL_CORRECT | **YES** |
| PRIMARY_ROOT_CAUSE | **CATEGORY_MAPPING_MISS** / OVER_ABSTENTION |

Title clearly names storm-sewer equipment; v6_1 map listed `дренаж/ливнев` but model still abstained. Not construction works.

### 27355 — gas metering verification (CLEAR_NEGATIVE FP)

| Field | Value |
|--|--|
| TITLE | Оказание услуг по проведению поверки газоанализаторов … газовых счетчиков … |
| OKPD | 71.12 — engineering/consulting services |
| FORM_PRIOR | DESIGN_ONLY |
| v6_1 MODEL_FORM | CONSTRUCTION_WORKS |
| v6_1 hyps | curbstone @0.4 CONTEXTUAL (confirmation_required=true) |
| v6_1 object | ROAD / ROAD_REPAIR — **copied from object example** |
| CURRENT_LABEL | EXPECTED_EMPTY |
| LABEL_CORRECT | **YES** |
| PRIMARY_ROOT_CAUSE | **EXAMPLE_LEAKAGE** (+ NEGATIVE_CONTRACT_FAILURE) |

Model ignored service evidence and emitted the OBJECT EXAMPLE skeleton (curbstone/road).

### 34517 — room repair at medical institute (labeled CLEAR_NEGATIVE FP)

| Field | Value |
|--|--|
| TITLE | Выполнение работ по текущему ремонту помещений … медико-фармацевтического института … |
| OKPD | 43.39.19.190 — finishing works |
| FORM_PRIOR | CONSTRUCTION_WORKS |
| v6_1 hyps | lighting @0.4 contextual |
| CURRENT_LABEL | CLEAR_NEGATIVE / EXPECTED_EMPTY |
| LABEL_CORRECT | **NO** |
| CORRECTED_LABEL | AMBIGUOUS_REVIEW / OBJECT_RELABELED |
| RATIONALE | Matched negative pattern via institute name `фармацевт`; procurement is room repair works, not an outside-registry product. Expectation of forced empty was incorrect. |
| PRIMARY_ROOT_CAUSE (of bad FP metric) | **LABEL_ERROR** (corpus); residual model issue = OBJECT_MODE_OVEREXPANSION / EXAMPLE_LEAKAGE (object_type ROAD for indoor rooms) |

## CALIBRATION_LABELS_REVALIDATED=YES

Only 34517 corrected in corpus. Hard CLEAR_NEGATIVE gate now excludes it.

## PROMPT_EXAMPLE_BIAS_FOUND=YES

PROMPT_BIAS_DETAILS:
1. OBJECT EXAMPLE filled with curbstone/ROAD_REPAIR → leaked into unrelated service (27355).
2. Positive map list omitted моноблок / storm-sewer equipment phrasing → over-abstention on true directs.
3. Negative rule too weak vs object-mode example gravity.
4. Form prior did not dominate 27355 (prior DESIGN_ONLY; model chose CONSTRUCTION_WORKS from example).

## Remediation in v6_2 (generalizable)

- STEP 1–6 decision order (what procured → form → direct map / object / services).
- Positive guard: explicit product → emit; no doc-required abstention.
- Negative guard: SERVICES_OTHER / metering verification → NO_COMMERCIAL_ENTRY.
- OBJECT EXAMPLE changed to bare road → empty + INSUFFICIENT_EVIDENCE (anti-leakage / anti-spam).
- Map patterns add моноблок and оборудование ливневой канализации.
