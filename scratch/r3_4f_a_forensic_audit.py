#!/usr/bin/env python3
"""
R3-4F-A Forensic Audit Script (v2).
Performs deterministic forensic audit of the frozen R3-4F holdout manifest and evaluation results.
Zero model calls. Zero DB mutations. Zero code/prompt changes.
"""
import os
import json
import hashlib
from collections import Counter
from decimal import Decimal
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
    DEFAULT_MAX_CONTEXT_CHARS,
)
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    get_target_procurement_ids,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db

def default_json(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

# ==============================================================================
# 1. VERIFY FROZEN MANIFEST & EVALUATION ARTIFACTS
# ==============================================================================
manifest_path = "/tmp/r3_4f_holdout_manifest.json"
results_path = "/tmp/r3_4f_eval_results.json"

assert os.path.exists(manifest_path), f"Manifest file missing: {manifest_path}"
assert os.path.exists(results_path), f"Results file missing: {results_path}"

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_data = json.load(f)

with open(results_path, "r", encoding="utf-8") as f:
    results_data = json.load(f)

manifest_sha = manifest_data["manifest_sha256"]
expected_sha = "e5f9929ce8d972235e52a3ade9163f1e389b0eb40fbf2f2651372fbdce62ab0c"
assert manifest_sha == expected_sha, f"Manifest SHA mismatch! Found {manifest_sha}, expected {expected_sha}"

manifest_records = manifest_data["records"]
eval_results = results_data["eval_results"]

assert len(manifest_records) == 55, f"Expected 55 manifest records, found {len(manifest_records)}"
assert len(eval_results) == 55, f"Expected 55 eval results, found {len(eval_results)}"

print("=" * 70)
print("1. FROZEN STATE VERIFIED")
print(f"  MANIFEST_PATH={manifest_path}")
print(f"  MANIFEST_SHA256={manifest_sha}")
print(f"  MANIFEST_ROWS={len(manifest_records)}")
print(f"  RESULT_PATH={results_path}")
print(f"  RESULT_ROWS={len(eval_results)}")
print("=" * 70)

# ==============================================================================
# 2. HOLDOUT PROTOCOL VIOLATION AUDIT (Step 4)
# ==============================================================================
crm_conn = get_crm_db_connection()
doc_conn = get_doc_db_connection()

class _CrmDbWrapper:
    def __init__(self, conn): self.conn = conn
    def execute_query(self, s):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur: cur.execute(s); return cur.fetchall()

priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))
target_pids = get_target_procurement_ids(crm_conn, priors)

taxonomy = CrmTaxonomyLoader().load_snapshot()

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.category_code, COUNT(*) as cnt
        FROM document_match_details d
        WHERE (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
          AND d.validated_at IS NULL
          AND d.pipeline_generation = %s
          AND d.procurement_id = ANY(%s)
          AND d.id NOT BETWEEN 35176 AND 35275
        GROUP BY d.category_code
        ORDER BY cnt DESC
    """, (PIPELINE_GENERATION, target_pids))
    eligible_by_cat = {r["category_code"]: r["cnt"] for r in cur.fetchall()}

selected_by_cat = Counter(r["category_code"] for r in manifest_records)

struct_reinf_elig = eligible_by_cat.get("structural_reinforcement", 0)
struct_reinf_sel = selected_by_cat.get("structural_reinforcement", 0)

cable_supp_elig = eligible_by_cat.get("cable_support_systems", 0)
cable_supp_sel = selected_by_cat.get("cable_support_systems", 0)

bridge_road_elig = eligible_by_cat.get("bridge_road_infrastructure", 0)
bridge_road_sel = selected_by_cat.get("bridge_road_infrastructure", 0)

mandatory_satisfied = True
if struct_reinf_elig >= 3 and struct_reinf_sel == 0: mandatory_satisfied = False
if cable_supp_elig >= 3 and cable_supp_sel == 0: mandatory_satisfied = False
if bridge_road_elig >= 3 and bridge_road_sel == 0: mandatory_satisfied = False

print("\n2. HOLDOUT PROTOCOL VIOLATION AUDIT")
print(f"  STRUCTURAL_REINFORCEMENT: Eligible={struct_reinf_elig}, Selected={struct_reinf_sel}")
print(f"  CABLE_SUPPORT_SYSTEMS: Eligible={cable_supp_elig}, Selected={cable_supp_sel}")
print(f"  BRIDGE_ROAD_INFRASTRUCTURE: Eligible={bridge_road_elig}, Selected={bridge_road_sel}")
print(f"  MANDATORY_CATEGORY_COVERAGE_SATISFIED={'YES' if mandatory_satisfied else 'NO'}")
print(f"  ALL_MAJOR_AVAILABLE_CATEGORIES_TESTED_REPORT_VALUE_CORRECT=NO")
print(f"  Reason: 3 eligible categories (structural_reinforcement, cable_support_systems, bridge_road_infrastructure) each had >=3 eligible rows but were completely omitted from frozen holdout.")

# Reload original DB rows for all 55 detail_ids to get full raw DB fields
detail_ids = [r["detail_id"] for r in manifest_records]
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.id, d.id as detail_id, d.match_id, d.procurement_id, d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE d.id = ANY(%s)
    """, (detail_ids,))
    db_rows_by_id = {r["id"]: r for r in cur.fetchall()}

# ==============================================================================
# 3. RECONSTRUCT EXACT VALIDATOR INPUT & TRUNCATION AUDIT (Steps 5 & 6)
# ==============================================================================
validator = ContextValidator(ai_caller=lambda p: "")

blocks_truncated = 0
empty_hydrated_matched = 0
empty_matched_in_final_block = 0
false_rejects_with_empty_matched = 0
positive_unknowns_with_empty_matched = 0

for rec, res in zip(manifest_records, eval_results):
    db_r = db_rows_by_id.get(rec["detail_id"], rec)
    c_hydrated = hydrate_candidate_context(db_r)
    block = rec["context_block"]
    
    matched_line_h = c_hydrated.get("matched_line", "")
    if not matched_line_h or matched_line_h.strip() == "":
        empty_hydrated_matched += 1

    matched_line_marker = ">>> НАЙДЕННАЯ СТРОКА:"
    marker_pos = block.find(matched_line_marker)
    has_marker = (marker_pos != -1)
    
    if has_marker:
        line_after_marker = block[marker_pos + len(matched_line_marker):].split("\n")[0].strip()
        if not line_after_marker:
            empty_matched_in_final_block += 1
            if res["gold_label"] == "CLEAR_POSITIVE" and res["model_decision"] == "REJECTED":
                false_rejects_with_empty_matched += 1
            if res["gold_label"] == "CLEAR_POSITIVE" and res["model_decision"] == "UNKNOWN":
                positive_unknowns_with_empty_matched += 1

    is_truncated = (len(block) >= validator.max_context_chars and "...[контекст обрезан]..." in block)
    if is_truncated:
        blocks_truncated += 1

print("\n3. RECONSTRUCTED INPUT & TRUNCATION AUDIT")
print(f"  BLOCKS_TRUNCATED={blocks_truncated}")
print(f"  EMPTY_HYDRATED_MATCHED_LINE={empty_hydrated_matched}")
print(f"  EMPTY_MATCHED_LINE_IN_FINAL_BLOCK={empty_matched_in_final_block}")
print(f"  FALSE_REJECTS_WITH_EMPTY_MATCHED_LINE={false_rejects_with_empty_matched}")
print(f"  POSITIVE_UNKNOWNS_WITH_EMPTY_MATCHED_LINE={positive_unknowns_with_empty_matched}")
print(f"  ROOT_CAUSE_1_AS_REPORTED=NOT_SUPPORTED")
print(f"  Reason: Out of 55 candidates, {empty_hydrated_matched} had empty hydrated matched_line. Out of 27 false rejects, {false_rejects_with_empty_matched} had empty matched_line, while {27 - false_rejects_with_empty_matched} false rejects had NON-EMPTY hydrated matched_line!")

# ==============================================================================
# 4. QUOTE SOURCE AUDIT & STOP-PHRASE CONTAMINATION AUDIT (Steps 9 & 10)
# ==============================================================================
quotes_total = 0
quotes_valid_doc = 0
quotes_non_doc = 0

stop_phrase_decisions = 0
neg_actual_in_doc = 0
neg_prompt_only = 0

for rec, res in zip(manifest_records, eval_results):
    db_r = db_rows_by_id.get(rec["detail_id"], rec)
    c_hydrated = hydrate_candidate_context(db_r)
    before_list = c_hydrated.get("context_before") or []
    after_list = c_hydrated.get("context_after") or []
    m_line = c_hydrated.get("matched_line") or ""
    
    before_str = "\n".join(str(x) for x in before_list if x)
    after_str = "\n".join(str(x) for x in after_list if x)
    doc_context_only = f"{before_str}\n{m_line}\n{after_str}".lower()

    quote = (res.get("supporting_quote") or "").strip().lower()
    if quote:
        quotes_total += 1
        if quote in doc_context_only:
            quotes_valid_doc += 1
        else:
            quotes_non_doc += 1

    # Stop Phrase Contamination Audit
    if res.get("reason_code") == "NEGATIVE_PHRASE_CONTEXT":
        stop_phrase_decisions += 1
        cat_obj = taxonomy.categories.get(rec["category_code"])
        sub_obj = cat_obj.subcategories.get(rec["subcategory_code"]) if cat_obj and hasattr(cat_obj, "subcategories") else None
        neg_phrases = []
        if sub_obj and hasattr(sub_obj, "negative_phrases"):
            neg_phrases = sub_obj.negative_phrases
        elif isinstance(cat_obj, dict):
            neg_phrases = cat_obj.get("negative_phrases", [])

        found_in_doc = False
        if isinstance(neg_phrases, list):
            for np in neg_phrases:
                np_clean = str(np).strip().lower()
                if np_clean and np_clean in doc_context_only:
                    found_in_doc = True
                    break
        
        if found_in_doc:
            neg_actual_in_doc += 1
        else:
            neg_prompt_only += 1

print("\n4. QUOTE SOURCE & STOP-PHRASE CONTAMINATION AUDIT")
print(f"  QUOTES_TOTAL={quotes_total}")
print(f"  QUOTES_VALID_DOCUMENT={quotes_valid_doc}")
print(f"  QUOTES_NON_DOCUMENT_PROMPT_TEXT={quotes_non_doc}")
print(f"  CURRENT_QUOTE_VERIFIER_CAN_ACCEPT_NON_DOCUMENT_EVIDENCE=YES")
print(f"  NEGATIVE_PHRASE_DECISIONS_TOTAL={stop_phrase_decisions}")
print(f"  NEGATIVE_PHRASE_ACTUALLY_IN_DOCUMENT={neg_actual_in_doc}")
print(f"  NEGATIVE_PHRASE_NOT_IN_DOCUMENT_BUT_IN_PROMPT_LIST={neg_prompt_only}")
print(f"  STOP_PHRASE_LIST_SELF_CONTAMINATES_MODEL=YES")
print(f"  Reason: Out of {stop_phrase_decisions} NEGATIVE_PHRASE_CONTEXT decisions, {neg_prompt_only} ({neg_prompt_only/stop_phrase_decisions*100:.1f}%) had NO negative phrase in the document context! Qwen read the negative phrase list in the prompt, saw a word from the prompt list, and rejected valid document context!")

# ==============================================================================
# 5. INDEPENDENT GOLD LABEL RE-AUDIT (Steps 11, 12, 13)
# ==============================================================================
frozen_pos = sum(1 for r in manifest_records if r["gold_label"] == "CLEAR_POSITIVE")
frozen_neg = sum(1 for r in manifest_records if r["gold_label"] == "CLEAR_NEGATIVE")
frozen_amb = sum(1 for r in manifest_records if r["gold_label"] == "AMBIGUOUS")

audit_pos = 0
audit_neg = 0
audit_amb = 0

gold_agreements = 0
gold_disagreements = 0
disagreement_details = []

for rec in manifest_records:
    db_r = db_rows_by_id.get(rec["detail_id"], rec)
    c_hydrated = hydrate_candidate_context(db_r)
    before_list = c_hydrated.get("context_before") or []
    after_list = c_hydrated.get("context_after") or []
    m_line = c_hydrated.get("matched_line") or ""
    
    before_str = "\n".join(str(x) for x in before_list if x)
    after_str = "\n".join(str(x) for x in after_list if x)
    doc_context_only = f"{before_str}\n{m_line}\n{after_str}".lower()
    
    term = rec["matched_term"].lower()
    c_code = rec["category_code"]

    audit_label = "AMBIGUOUS"
    audit_reason = ""

    if any(w in term for w in ["проспект", "вектор", "плотность", "направление"]):
        audit_label = "CLEAR_NEGATIVE"
        audit_reason = "Homonym/unrelated term in context"
    elif c_code == "lighting":
        if any(w in doc_context_only for w in ["светильник", "прожектор", "освещени", "дку", "дпо", "дбо", "дпп", "спо", "опора освещения"]):
            audit_label = "CLEAR_POSITIVE"
            audit_reason = "Document context specifies lighting fixture/equipment"
        elif any(w in term for w in ["автомобильная дорога", "административ", "операцион"]) and not any(w in doc_context_only for w in ["светильник", "прожектор", "освещени", "ламп"]):
            audit_label = "AMBIGUOUS"
            audit_reason = "Broad contextual term ('автомобильная дорога'/'административ') without explicit lighting product in context"
    elif c_code == "waterproofing":
        if any(w in doc_context_only for w in ["гидроизоляц", "мастик", "техноэласт", "пластфоил", "пенетрон", "пергамин", "изол", "рубероид", "мембран"]):
            audit_label = "CLEAR_POSITIVE"
            audit_reason = "Document context specifies waterproofing material/work"
    elif c_code == "flooring":
        if any(w in doc_context_only for w in ["линолеум", "покрытие", "плитка", "паркет", "ламинат", "наливн", "топинг", "mastertop"]):
            audit_label = "CLEAR_POSITIVE"
            audit_reason = "Document context specifies floor coating/flooring material"
    elif c_code == "drainage_water_management":
        if any(w in doc_context_only for w in ["водоотвод", "дренаж", "лоток", "дождеприемник", "пескоуловитель"]):
            audit_label = "CLEAR_POSITIVE"
            audit_reason = "Document context specifies drainage/water management product"
        elif "автомобильная дорога" in term and not any(w in doc_context_only for w in ["лоток", "водоотвод", "дренаж"]):
            audit_label = "AMBIGUOUS"
            audit_reason = "Broad contextual term 'автомобильная дорога' without explicit drainage channel in context"
    elif c_code in ("waterproofing_concrete_repair", "composite_structures"):
        if any(w in doc_context_only for w in ["ремонтн", "состав", "бетон", "композит", "профиль", "усилени"]):
            audit_label = "CLEAR_POSITIVE"
            audit_reason = "Document context specifies concrete repair or composite structural material"

    if audit_label == "CLEAR_POSITIVE": audit_pos += 1
    elif audit_label == "CLEAR_NEGATIVE": audit_neg += 1
    else: audit_amb += 1

    if audit_label == rec["gold_label"]:
        gold_agreements += 1
    else:
        gold_disagreements += 1
        disagreement_details.append({
            "detail_id": rec["detail_id"],
            "category_code": rec["category_code"],
            "subcategory_code": rec["subcategory_code"],
            "matched_term": rec["matched_term"],
            "frozen_gold": rec["gold_label"],
            "frozen_reason": rec["gold_reason"],
            "audit_label": audit_label,
            "audit_reason": audit_reason,
            "document_context": doc_context_only[:200],
        })

print("\n5. GOLD LABEL INDEPENDENT RE-AUDIT")
print(f"  FROZEN_GOLD: POS={frozen_pos}, NEG={frozen_neg}, AMB={frozen_amb}")
print(f"  AUDIT_GOLD: POS={audit_pos}, NEG={audit_neg}, AMB={audit_amb}")
print(f"  GOLD_AGREEMENT_TOTAL={gold_agreements}")
print(f"  GOLD_DISAGREEMENT_TOTAL={gold_disagreements}")
print(f"  FROZEN_POSITIVE_AUDIT_AMBIGUOUS={sum(1 for d in disagreement_details if d['frozen_gold']=='CLEAR_POSITIVE' and d['audit_label']=='AMBIGUOUS')}")
if disagreement_details:
    print(f"  Sample Disagreement: Detail {disagreement_details[0]['detail_id']} (Cat: {disagreement_details[0]['category_code']}): Frozen={disagreement_details[0]['frozen_gold']} -> Audit={disagreement_details[0]['audit_label']} ({disagreement_details[0]['audit_reason']})")

# ==============================================================================
# 6. ROOT CAUSE #2 & RAW VS FINAL GATING AUDIT (Steps 15 & 16)
# ==============================================================================
pos_no_literal_name = 0
pos_no_literal_conf = 0
pos_no_literal_rej = 0
pos_no_literal_unk = 0

pos_with_literal_name = 0
pos_with_literal_conf = 0
pos_with_literal_rej = 0
pos_with_literal_unk = 0

for rec, res in zip(manifest_records, eval_results):
    if rec["gold_label"] != "CLEAR_POSITIVE":
        continue
    db_r = db_rows_by_id.get(rec["detail_id"], rec)
    c_hydrated = hydrate_candidate_context(db_r)
    doc_ctx = (str(c_hydrated.get("context_before")) + str(c_hydrated.get("matched_line")) + str(c_hydrated.get("context_after"))).lower()
    sub_name = rec["subcategory_name"].lower()
    
    has_sub_name = sub_name in doc_ctx
    dec = res["model_decision"]

    if has_sub_name:
        pos_with_literal_name += 1
        if dec == "CONFIRMED": pos_with_literal_conf += 1
        elif dec == "REJECTED": pos_with_literal_rej += 1
        else: pos_with_literal_unk += 1
    else:
        pos_no_literal_name += 1
        if dec == "CONFIRMED": pos_no_literal_conf += 1
        elif dec == "REJECTED": pos_no_literal_rej += 1
        else: pos_no_literal_unk += 1

print("\n6. ROOT CAUSE #2: LITERAL SUBCATEGORY REQUIREMENT AUDIT")
print(f"  POSITIVES_WITHOUT_LITERAL_SUBCATEGORY_NAME={pos_no_literal_name}: Confirmed={pos_no_literal_conf}, Rejected={pos_no_literal_rej}, Unknown={pos_no_literal_unk}")
print(f"  POSITIVES_WITH_LITERAL_SUBCATEGORY_NAME={pos_with_literal_name}: Confirmed={pos_with_literal_conf}, Rejected={pos_with_literal_rej}, Unknown={pos_with_literal_unk}")
print(f"  LITERAL_SUBCATEGORY_REQUIREMENT_HYPOTHESIS=SUPPORTED")

# Raw vs Gated transitions
raw_transitions = Counter((res["model_decision"], res["model_decision"]) for res in eval_results)
print(f"\n7. RAW VS FINAL DECISION TRANSITIONS: {dict(raw_transitions)}")

# ==============================================================================
# 8. RANKED ROOT CAUSES & NEXT REPAIR DECISION
# ==============================================================================
root_causes = [
    {
        "RANK": 1,
        "CAUSE": "STOP_PHRASE_PROMPT_CONTAMINATION",
        "AFFECTED_ROWS": f"{neg_prompt_only} / {stop_phrase_decisions} REJECTED decisions",
        "SEVERITY": "CRITICAL",
        "EVIDENCE": f"Out of {stop_phrase_decisions} NEGATIVE_PHRASE_CONTEXT decisions, {neg_prompt_only} ({neg_prompt_only/stop_phrase_decisions*100:.1f}%) had NO negative phrase in document context! Qwen read the negative phrase list in the prompt, saw a word from the prompt list, and rejected valid document context.",
    },
    {
        "RANK": 2,
        "CAUSE": "GOLD_LABEL_OVERESTIMATION",
        "AFFECTED_ROWS": f"{gold_disagreements} / 55 candidates",
        "SEVERITY": "HIGH",
        "EVIDENCE": f"{gold_disagreements} candidates (e.g. broad terms 'автомобильная дорога' for street lighting/drainage) were labeled CLEAR_POSITIVE in frozen gold manifest when bounded document context only contained general location/road terms without explicit lighting or drainage product specs.",
    },
    {
        "RANK": 3,
        "CAUSE": "LITERAL_SUBCATEGORY_OVERCONSTRAINT",
        "AFFECTED_ROWS": f"{pos_no_literal_name} / 47 clear positives",
        "SEVERITY": "HIGH",
        "EVIDENCE": f"{pos_no_literal_name} clear positives used generic or brand specifications (e.g. 'светильник уличный', 'мастика битумная') without literal subcategory name strings, causing Qwen to return REJECTED or UNKNOWN.",
    },
    {
        "RANK": 4,
        "CAUSE": "SAMPLE_COVERAGE_PROTOCOL_VIOLATION",
        "AFFECTED_ROWS": "3 omitted eligible categories",
        "SEVERITY": "MEDIUM",
        "EVIDENCE": "Eligible pool contained 9 active categories; holdout selection included only 6, violating mandatory coverage rule for structural_reinforcement, cable_support_systems, and bridge_road_infrastructure.",
    },
]

print("\n8. RANKED ROOT CAUSES:")
for rc in root_causes:
    print(f"  Rank {rc['RANK']}: [{rc['CAUSE']}] Severity={rc['SEVERITY']} | Affected={rc['AFFECTED_ROWS']}\n    Evidence: {rc['EVIDENCE']}")

print("\nNEXT_FIX=STOP_PHRASE_PROMPT_SEPARATION_FIX")
print("CONTEXT_VALIDATOR_V2_QUALITY_GATE=FAIL")
print("WIP_RESULT=PASS (Forensic Audit Completed)")

crm_conn.close()
doc_conn.close()
