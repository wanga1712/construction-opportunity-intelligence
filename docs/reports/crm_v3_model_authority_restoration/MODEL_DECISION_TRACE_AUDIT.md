# MODEL_DECISION_TRACE_AUDIT.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1` / **PHASE 8** (audit only)

## Authority

| Item | Value |
|--|--|
| PRODUCTION_MODEL | qwen2.5:7b |
| PRODUCTION_PROMPT_VERSION | v3_category_centric_routing_7b_v5 |
| AUDIT_SHADOW_PROMPT | v3_category_centric_routing_7b_v6_1 (Phase 7/7.1 immutable) |
| MODEL_INPUT_VERSION | V3_ROUTING_MODEL_INPUT_V3 |
| MODEL_VALIDATED_MUTATED | NO |
| PRODUCTION_MUTATIONS | 0 |

Phase 8 does **not** change production prompt/model. Residual forensics use frozen SHADOW v6_1 runs.

## Pipeline (proven)

```
SOURCE FACTS
→ CANONICAL CARD (V2)
→ V3_ROUTING_MODEL_INPUT_V3
→ PYTHON priors / form prior / title hints / OKPD priors (prompt-adjacent)
→ EXACT QWEN PROMPT (v5 prod / v6_1 audit shadow)
→ RAW MODEL RESPONSE (immutable crm_v3_model_inference_runs.raw_model_json)
→ VALIDATED MODEL RESULT (registry allow-list filter; no invention)
→ BUSINESS POSTPROCESSING (contextual priors, scores, medals) — separate attribution
→ UI projection
```

Document content is **not** in first-pass routing input (counts only).

---

## CASE 23591 — pipeline dump

Expert label: `EXPECTED_EXACT_CATEGORY=drainage_water_management`  
Evidence base: immutable SHADOW `inference_run_id=283` (`v3_category_centric_routing_7b_v6_1`) + Phase 7.1 re-run `476` + forensic rebuild in `_phase71_forensic.json`  
SHADOW only: YES (not production-authoritative)

### SOURCE FACTS

| Field | Value | Kind |
|--|--|--|
| title | Поставка оборудования ливневой канализации БМК Сосневская, г. Иваново 2026 г. для нужд филиала "Владимирский" ПАО "Т Плюс"(ИвТС) (4548581) | SOURCE FACT |
| official_description | null | SOURCE_NOT_AVAILABLE |
| OKPD code | 22.23.13.194 | SOURCE FACT |
| OKPD name | Резервуары, цистерны, баки и аналогичные емкости пластмассовые вместимостью свыше 300 л из поливинилхлорида | SOURCE FACT |
| all exact OKPD | ["22.23.13.194"] | SOURCE FACT |
| price | 1659743.39 | SOURCE FACT |
| law | 223_FZ / CORPORATE_223FZ | SOURCE FACT / DERIVED contour |
| customer | ПАО "Т ПЛЮС" | SOURCE FACT |
| region | delivery_region text "Московская область"; address Иваново | SOURCE FACT (inconsistent geography in source) |
| lifecycle | WAITING_SOURCE_OUTCOME | DERIVED |
| source identity | reestr_contract_223_fz / source_id=156304 / contract 32616265292 | SOURCE FACT |

### CANONICAL CARD

Card version V2. Relevant fields before model-input reduction:

- SOURCE FACT: title, OKPD, price, customer, tender_link, document_links_summary (2 zip names/URLs on card)
- DERIVED: normalized_lifecycle, tender_clock, commercial_timing_value, routing_ready=false (WAITING_NOT_ROUTABLE), region_provenance=SOURCE_DELIVERY_REGION
- official_description_provenance=`SOURCE_NOT_AVAILABLE`

`document_links_summary` exists on the **card** but is **stripped** from `V3_ROUTING_MODEL_INPUT_V3` (counts only).

### PYTHON BEFORE MODEL

| Signal | Value | VISIBLE_TO_MODEL |
|--|--|--|
| procurement_form_prior | DIRECT_GOODS_PURCHASE | YES (heuristic form prior in prompt) |
| commercial_product_priors | [] | YES (empty list in model input JSON) |
| contextual_research_priors | [] | YES (empty) |
| title_hints | [drainage_water_management] | YES (drives subcategory exposure; category listed in registry block) |
| OKPD prior matches | [] | YES (empty priors JSON in prompt) |
| allowed registry categories | includes drainage_water_management; does **not** include `cable` | YES |
| subcategory details | exposed for hint-supported drainage | YES (compact registry) |
| DIRECT_CABLE_EXPECTED_RESULT | NO_COMMERCIAL_ENTRY | YES |
| document counts | link=2 unique=2 | YES |

### ACTUAL MODEL INPUT

- model_input_version=`V3_ROUTING_MODEL_INPUT_V3`
- model_input_hash=`3b7aa959b14d028d7376bf478bc09384d2109bd40d41266ae6b4dff2f9237678`
- Exact persisted/rebuilt object in forensic `MODEL_INPUT.v3_model_input` (not approximated).

### ACTUAL MODEL QUESTION / PROMPT

- prompt_version=`v3_category_centric_routing_7b_v6_1`
- prompt size≈21203 chars (forensic rebuild)
- model=`qwen2.5:7b`
- prompt_hash on run 283: see immutable dump

What Qwen was asked:

1. Yes — understand the literal purchased item (MODE A / DIRECT map from title).
2. Also anchored toward object-mode via OBJECT EXAMPLE (curbstone/ROAD) in the same prompt.
3. `drainage_water_management` present in: commercial registry YES; OKPD prior NO; contextual prior NO; title hint YES.
4. Lighting / cable_support examples are salient in POSITIVE EXAMPLE blocks; map rule includes `дренаж/ливнев→drainage_water_management` and `кабельн* лоток→cable_support_systems`.

### RAW MODEL RESPONSE (run 283)

```json
{
  "brands": [],
  "work_methods": [],
  "analysis_modes": [
    "DIRECT_PRODUCT"
  ],
  "object_context": [],
  "source_contour": "CORPORATE_223FZ",
  "material_signals": [],
  "procurement_form": "DIRECT_GOODS_PURCHASE",
  "application_areas": [],
  "discovery_required": false,
  "object_classification": {
    "work_stage": "SUPPLY",
    "object_type": "GOODS",
    "object_sector": "SUPPLY",
    "object_context": [],
    "object_subtype": "CABLE"
  },
  "empty_hypothesis_status": null,
  "overall_research_action": "LIGHT_RESEARCH",
  "document_research_priority": [],
  "preferred_opportunity_track": null,
  "empty_hypothesis_reason_codes": [],
  "commercial_category_hypotheses": [
    {
      "confidence": 0.8,
      "reason_codes": [
        "title_product_match"
      ],
      "category_code": "cable",
      "evidence_role": "DIRECT_CATEGORY_EVIDENCE",
      "research_action": "LIGHT_RESEARCH",
      "subcategory_code": "SUBCATEGORY_NOT_ASSIGNED",
      "opportunity_track": "DIRECT_SUPPLY",
      "confirmation_required": false
    }
  ]
}
```

Phase 7.1 re-run 476 RAW categories: `["equipment"]`, object_subtype=`EQUIPMENT` (also invalid; still not drainage).

### VALIDATED MODEL

```json
{
  "brands": [],
  "work_methods": [],
  "analysis_modes": [
    "DIRECT_PRODUCT"
  ],
  "object_context": [],
  "schema_version": "v3_model_validated_1",
  "source_contour": "CORPORATE_223FZ",
  "material_signals": [],
  "procurement_form": "DIRECT_GOODS_PURCHASE",
  "application_areas": [],
  "discovery_required": false,
  "object_classification": {
    "work_stage": "SUPPLY",
    "object_type": "GOODS",
    "object_sector": "SUPPLY",
    "object_context": [],
    "object_subtype": "CABLE"
  },
  "empty_hypothesis_status": null,
  "overall_research_action": "LIGHT_RESEARCH",
  "document_research_priority": [],
  "preferred_opportunity_track": null,
  "empty_hypothesis_reason_codes": [],
  "commercial_category_hypotheses": []
}
```

| Check | Value |
|--|--|
| RAW_CATEGORY | cable |
| VALIDATED_CATEGORY | (empty) |
| RAW_CATEGORY_VALID_IN_REGISTRY | NO |
| VALIDATOR_REMOVED_CATEGORY | YES |
| VALIDATOR_CHANGED_SEMANTICS | YES (non-empty → empty) |
| empty_hypothesis_status | null (contract-invalid for empty hyps) |

### BUSINESS AFTER MODEL

No `procurement_ai_assessments` row linked for these SHADOW-only procurements in the Phase 8 dump (`assessments=0`).  
Therefore: no business_rule_result / medal / score applied for this SHADOW inference.  
Contextual prior additions: none observed on assessment row.

### FINAL UI

If this inference were production-authoritative, operator would see **empty MODEL_VALIDATED categories** (not `cable`).  
Inference is **SHADOW only** — not publication authority.

| Layer | 23591 |
|--|--|
| SOURCE | title storm-sewer equipment + OKPD plastic tanks |
| MODEL_VALIDATED | hypotheses=[] |
| BUSINESS_RULE | not applied (SHADOW; no assessment row) |
| PRESENTATION | would show empty model categories |

### ROOT CAUSE — CASE 23591

```
SOURCE_DATA_GAP=NO
MODEL_INPUT_GAP=NO
PYTHON_PREBIAS=NO
PROCUREMENT_FORM_ERROR=NO
OBJECT_CLASSIFICATION_ERROR=YES  # subtype CABLE vs storm-sewer equipment
ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR=YES
CATEGORY_MAPPING_ERROR=NO
INVALID_REGISTRY_CODE_GENERATION=YES
VALIDATOR_REJECTED_MODEL_CATEGORY=YES
ABSTENTION_ERROR=YES
OBJECT_PRIOR_OVERREACH=NO
POST_MODEL_BUSINESS_ERROR=NO
PRESENTATION_ERROR=NO
```

**CASE_23591_PRIMARY_ROOT_CAUSE=`ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR`**

Concise: model did not treat the purchase as storm-drainage equipment mapping to the visible registry code; it asserted a wrong product family (`cable` / later `equipment`). This is **not** a computers↔computer_components style taxonomy near-miss.

---

## COMPARE 37082 VS 23591

| Dimension | 37082 | 23591 |
| --- | --- | --- |
| Source sufficient? | YES | YES |
| Correct procurement form? | YES (DIRECT_GOODS_PURCHASE) | YES (DIRECT_GOODS_PURCHASE) |
| Model understood literal item? | YES (computer/monoblock family) | NO (RAW subtype CABLE / later EQUIPMENT) |
| Model understood object? | N/A (goods supply) | N/A (goods supply) |
| Correct registry category visible? | YES (computers) | YES (drainage_water_management) |
| Correct category prior visible? | YES (OKPD prior computers + title_hints) | YES (title_hints=[drainage_water_management]; OKPD priors=[]) |
| Model emitted semantic equivalent? | NEAR (computer_components) | NO (cable / equipment) |
| Model emitted invalid code? | YES | YES |
| Validator caused empty result? | YES | YES |
| True abstention? | NO | NO |
| Primary failure class | CATEGORY_MAPPING_ERROR | ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR |

**DO_37082_AND_23591_SHARE_THE_SAME_FAILURE_MECHANISM=`NO`**

Shared surface only: invalid RAW code → validator empty. Root mechanisms differ (mapping near-miss vs item-family misunderstanding).

---

## Corpus summary (n=34)

| Bucket | Count |
|--|--|
| DIRECT | 11 |
| NEGATIVE | 11 |
| OBJECT | 10 |

Primary root-cause distribution:

| PRIMARY_ROOT_CAUSE | N |
| --- | --- |
| NO_ERROR | 13 |
| INVALID_REGISTRY_CODE_GENERATION | 13 |
| OBJECT_PRIOR_OVERREACH | 3 |
| ABSTENTION_ERROR | 3 |
| CATEGORY_MAPPING_ERROR | 1 |
| ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR | 1 |

Machine-readable: `model_decision_trace_cases.json`

### Focus companions

| Case | Expected | RAW | VALIDATED | Primary |
|--|--|--|--|--|
| 37082 | computers | computer_components | [] | CATEGORY_MAPPING_ERROR |
| 23591 | drainage_water_management | cable | [] | ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR |
| 27355 | empty | curbstone | curbstone | OBJECT_PRIOR_OVERREACH |
| 34517 | OBJECT_RELABELED | lighting | lighting | OBJECT_PRIOR_OVERREACH |

---

## PHASE_8 final report

```
PHASE_8=PASS

TRACED_CASES=34
DIRECT_CASES=11
NEGATIVE_CASES=11
OBJECT_CASES=10

MODEL_INPUT_VERSION=V3_ROUTING_MODEL_INPUT_V3
PRODUCTION_MODEL=qwen2.5:7b
PRODUCTION_PROMPT_VERSION=v3_category_centric_routing_7b_v5

DOCUMENT_CONTENT_SENT_TO_ROUTING_MODEL=NO
DOCUMENT_TEXT_SENT_TO_ROUTING_MODEL=NO
DOCUMENT_NAMES_SENT_TO_ROUTING_MODEL=NO
DOCUMENT_EVIDENCE_SENT_TO_ROUTING_MODEL=NO

PREMODEL_PYTHON_SIGNALS_VISIBLE_TO_MODEL=YES
  (form prior, COMMERCIAL_PRODUCT_PRIORS, CONTEXTUAL_RESEARCH_PRIORS,
   OKPD priors JSON, title_hints→subcategory exposure, DIRECT_CABLE_EXPECTED_RESULT,
   document_link_count/unique_document_count)

DISTINCT_MODEL_DECISIONS=10
QUESTIONS_REQUIRING_UNSEEN_DOCUMENTS=document_research_priority; contextual confirmation_required; MODE-B “confirmed in documents”

ACTUAL_PURCHASE_VS_REGISTRY_MAPPING_MIXED=YES
ACTUAL_PURCHASE_VS_OBJECT_PRIOR_MIXED=YES
OBJECT_PRIOR_VS_CONFIRMED_DOCUMENT_EVIDENCE_MIXED=YES

CASE_37082_PRIMARY_ROOT_CAUSE=CATEGORY_MAPPING_ERROR
CASE_23591_PRIMARY_ROOT_CAUSE=ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR
DO_37082_AND_23591_SHARE_THE_SAME_FAILURE_MECHANISM=NO

SOURCE_DATA_GAP_CASES=[]
MODEL_INPUT_GAP_CASES=[]
PYTHON_PREBIAS_CASES=[]

ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR_CASES=[23591] (+ secondary flags; see JSON)
CATEGORY_MAPPING_ERROR_CASES=[37082]
INVALID_REGISTRY_CODE_GENERATION_CASES=see model_decision_trace_cases.json flag_case_lists (n=13 primary)
VALIDATOR_REJECTED_MODEL_CATEGORY_CASES=see flag_case_lists
ABSTENTION_ERROR_CASES=see flag_case_lists
OBJECT_PRIOR_OVERREACH_CASES=[27355,34517,31936]
POST_MODEL_BUSINESS_ERROR_CASES=[]

MODEL_VALIDATED_MUTATED=NO
PRODUCTION_MODEL_CHANGED=NO
PRODUCTION_PROMPT_CHANGED=NO
PRODUCTION_MUTATIONS=0

TESTS=test_v3_phase8_decision_trace_audit.py PASS (2)
REPO_HYGIENE_CHECK=PASS (Phase 8 artifacts only staged)

AUDIT_COMMIT=<set on commit>

PHASE_8=PASS
```

**STOP.** No architecture implementation until operator reviews the failure distribution.
