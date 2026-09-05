#!/usr/bin/env python3
"""
R3-4F Step 11: Finalize Gold Label Manifest for Cohorts A, B, C.
Inspects context_block for each selected candidate and assigns gold_label & gold_reason BEFORE running Qwen.
Saves frozen manifest to /tmp/r3_4f_holdout_manifest.json and calculates MANIFEST_SHA256.
"""
import os
import json
import hashlib
from decimal import Decimal
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    get_target_procurement_ids,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db

def default_json(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

crm_conn = get_crm_db_connection()
doc_conn = get_doc_db_connection()

class _CrmDbWrapper:
    def __init__(self, conn): self.conn = conn
    def execute_query(self, s):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur: cur.execute(s); return cur.fetchall()

priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))
target_pids = get_target_procurement_ids(crm_conn, priors)

taxonomy = CrmTaxonomyLoader().load_snapshot()
cat_names = {}
sub_names = {}
for code, cat in taxonomy.categories.items():
    c_name = getattr(cat, "category_name", None) or getattr(cat, "name", None) or (cat.get("category_name") if isinstance(cat, dict) else str(code))
    cat_names[code] = c_name
    subs = getattr(cat, "subcategories", {}) if not isinstance(cat, dict) else cat.get("subcategories", {})
    if isinstance(subs, dict):
        for sub_code, sub in subs.items():
            s_name = getattr(sub, "subcategory_name", None) or getattr(sub, "name", None) or (sub.get("subcategory_name") if isinstance(sub, dict) else str(sub_code))
            sub_names[sub_code] = s_name

# Fetch all eligible candidates from DB
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.id, d.id as detail_id, d.match_id, d.procurement_id, d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score, d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
          AND d.validated_at IS NULL
          AND d.pipeline_generation = %s
          AND d.procurement_id = ANY(%s)
          AND d.id NOT BETWEEN 35176 AND 35275
        ORDER BY d.id ASC
    """, (PIPELINE_GENERATION, target_pids))
    eligible_rows = cur.fetchall()

validator = ContextValidator(ai_caller=lambda p: "")
by_id = {}
for r in eligible_rows:
    r["category_name"] = cat_names.get(r["category_code"], r["category_code"])
    r["subcategory_name"] = sub_names.get(r["subcategory_code"], r["subcategory_code"])
    r["context_block"] = validator.build_context_block(r)
    by_id[r["id"]] = r

# ==============================================================================
# 1. COHORT A — NATURAL STRATIFIED (30 rows)
# Selected deterministically via SHA256 sort
# ==============================================================================
cat_targets_A = {
    "lighting": 12,
    "waterproofing": 6,
    "flooring": 5,
    "drainage_water_management": 4,
    "waterproofing_concrete_repair": 2,
    "composite_structures": 1,
}

hashed_candidates = []
for r in eligible_rows:
    h_str = f"R3-4F-NATURAL-V1:{r['id']}:{r['procurement_id']}"
    h_val = hashlib.sha256(h_str.encode("utf-8")).hexdigest()
    hashed_candidates.append((h_val, r))
hashed_candidates.sort(key=lambda x: x[0])

cohort_A = []
selected_ids = set()
procurement_counts = {}
cat_selected_A = {c: 0 for c in cat_targets_A}

for h_val, r in hashed_candidates:
    c_code = r["category_code"]
    pid = r["procurement_id"]
    if c_code not in cat_targets_A:
        continue
    if cat_selected_A[c_code] >= cat_targets_A[c_code]:
        continue
    if procurement_counts.get(pid, 0) >= 3:
        continue
    
    r_entry = dict(r)
    r_entry["cohort"] = "NATURAL_STRATIFIED"
    cohort_A.append(r_entry)
    selected_ids.add(r["id"])
    cat_selected_A[c_code] += 1
    procurement_counts[pid] = procurement_counts.get(pid, 0) + 1
    if len(cohort_A) >= 30:
        break

# Assign Gold Labels for Cohort A based strictly on bounded context_block
for r in cohort_A:
    ctx = r["context_block"].lower()
    term = r["matched_term"].lower()
    c_code = r["category_code"]
    
    if c_code == "lighting":
        if any(w in ctx for w in ["светильник", "прожектор", "освещени", "дку", "дпо", "дбо", "дпп", "спо", "опора освещения"]):
            r["gold_label"] = "CLEAR_POSITIVE"
            r["gold_reason"] = "Context contains explicit lighting product/equipment specifications or BOQ row"
        elif any(w in ctx for w in ["вектор", "директор", "проспект"]):
            r["gold_label"] = "CLEAR_NEGATIVE"
            r["gold_reason"] = "Context term is unrelated non-lighting word"
        else:
            r["gold_label"] = "AMBIGUOUS"
            r["gold_reason"] = "Context contains generic term without full specification"
            
    elif c_code == "waterproofing":
        if any(w in ctx for w in ["гидроизоляц", "мастик", "техноэласт", "пластфоил", "пенетрон", "пергамин", "изол", "рубероид", "мембран"]):
            r["gold_label"] = "CLEAR_POSITIVE"
            r["gold_reason"] = "Context contains explicit waterproofing material/work specification"
        elif any(w in ctx for w in ["плотность", "направление"]):
            r["gold_label"] = "CLEAR_NEGATIVE"
            r["gold_reason"] = "Context contains non-waterproofing measurement"
        else:
            r["gold_label"] = "AMBIGUOUS"
            r["gold_reason"] = "Context contains generic term without explicit specification"

    elif c_code == "flooring":
        if any(w in ctx for w in ["покрытие", "линолеум", "ламинат", "плитка", "паркет", "наливн", "топинг", "mastertop"]):
            r["gold_label"] = "CLEAR_POSITIVE"
            r["gold_reason"] = "Context contains explicit floor coating/flooring specification"
        else:
            r["gold_label"] = "AMBIGUOUS"
            r["gold_reason"] = "Context contains generic word without explicit flooring specification"

    elif c_code == "drainage_water_management":
        if any(w in ctx for w in ["водоотвод", "дренаж", "лоток", "дождеприемник", "пескоуловитель"]):
            r["gold_label"] = "CLEAR_POSITIVE"
            r["gold_reason"] = "Context contains explicit drainage/water management product or work"
        else:
            r["gold_label"] = "AMBIGUOUS"
            r["gold_reason"] = "Context contains generic drainage term"

    elif c_code in ("waterproofing_concrete_repair", "composite_structures"):
        if any(w in ctx for w in ["ремонтн", "состав", "бетон", "композит", "профиль", "усилени"]):
            r["gold_label"] = "CLEAR_POSITIVE"
            r["gold_reason"] = "Context contains explicit concrete repair or composite structural material"
        else:
            r["gold_label"] = "AMBIGUOUS"
            r["gold_reason"] = "Context contains generic material term"
    else:
        r["gold_label"] = "AMBIGUOUS"
        r["gold_reason"] = "Default ambiguous context evaluation"

# ==============================================================================
# 2. COHORT B — CLEAR POSITIVE CHALLENGE (20 rows)
# Clear positive context across >=5 categories, >=8 procurements, max 2 per procurement
# ==============================================================================
cohort_B_ids = []
cat_counts_B = {}

for r in eligible_rows:
    if r["id"] in selected_ids:
        continue
    pid = r["procurement_id"]
    if procurement_counts.get(pid, 0) >= 3:
        continue
    c_code = r["category_code"]
    if cat_counts_B.get(c_code, 0) >= 5:
        continue

    ctx = r["context_block"].lower()
    is_pos = False
    reason = ""
    
    if c_code == "lighting" and any(w in ctx for w in ["светильник", "прожектор", "освещени", "ламп"]):
        is_pos = True
        reason = "Clear lighting fixture/equipment context"
    elif c_code == "waterproofing" and any(w in ctx for w in ["гидроизоляц", "мастик", "техноэласт", "пластфоил", "пенетрон", "мембран"]):
        is_pos = True
        reason = "Clear waterproofing material/work context"
    elif c_code == "flooring" and any(w in ctx for w in ["линолеум", "покрытие", "плитка", "паркет", "ламинат"]):
        is_pos = True
        reason = "Clear flooring material/coating context"
    elif c_code == "drainage_water_management" and any(w in ctx for w in ["водоотвод", "лоток", "дождеприемник", "дренаж"]):
        is_pos = True
        reason = "Clear drainage channel/water management context"
    elif c_code == "waterproofing_concrete_repair" and any(w in ctx for w in ["ремонтн", "состав", "бетон", "омоноличивание"]):
        is_pos = True
        reason = "Clear concrete repair mortar context"
    elif c_code == "composite_structures" and any(w in ctx for w in ["композит", "профиль", "пултрузи"]):
        is_pos = True
        reason = "Clear composite structural profile context"
    elif c_code == "cable_support_systems" and any(w in ctx for w in ["лоток", "кабельн"]):
        is_pos = True
        reason = "Clear cable support system context"
    elif c_code == "bridge_road_infrastructure" and any(w in ctx for w in ["мост", "сход", "лестниц"]):
        is_pos = True
        reason = "Clear bridge/road infrastructure walkway context"
    elif c_code == "structural_reinforcement" and any(w in ctx for w in ["усилен", "холст", "углерод"]):
        is_pos = True
        reason = "Clear structural reinforcement carbon fiber context"

    if is_pos:
        r_entry = dict(r)
        r_entry["cohort"] = "CLEAR_POSITIVE_CHALLENGE"
        r_entry["gold_label"] = "CLEAR_POSITIVE"
        r_entry["gold_reason"] = reason
        cohort_B_ids.append(r_entry)
        selected_ids.add(r["id"])
        cat_counts_B[c_code] = cat_counts_B.get(c_code, 0) + 1
        procurement_counts[pid] = procurement_counts.get(pid, 0) + 1
        if len(cohort_B_ids) >= 20:
            break

print(f"Cohort B selected: {len(cohort_B_ids)} rows across categories: {list(cat_counts_B.keys())}")

# ==============================================================================
# 3. COHORT C — NEGATIVE / AMBIGUOUS CHALLENGE (10 rows)
# 5 CLEAR_NEGATIVE + 5 AMBIGUOUS across >=4 categories
# ==============================================================================
cohort_C_ids = []
negs_picked = 0
ambs_picked = 0

for r in eligible_rows:
    if r["id"] in selected_ids:
        continue
    pid = r["procurement_id"]
    if procurement_counts.get(pid, 0) >= 3:
        continue

    ctx = r["context_block"].lower()
    term = r["matched_term"].lower()
    c_code = r["category_code"]
    
    label = None
    reason = ""
    
    # 1. Clear Negatives (homonym / unrelated matches)
    if negs_picked < 5:
        if "вектор" in term or "проспект" in ctx or "плотность" in term or "направление" in ctx or "директор" in ctx:
            label = "CLEAR_NEGATIVE"
            reason = "Matched term/context is homonym or unrelated word"
            negs_picked += 1
            
    # 2. Ambiguous cases (short codes, generic single-words)
    if not label and ambs_picked < 5:
        if len(term) <= 3 and len(ctx.split()) < 12:
            label = "AMBIGUOUS"
            reason = "Short term abbreviation with insufficient context to decide category safely"
            ambs_picked += 1
        elif "устройство" in term and not any(w in ctx for w in ["покрытие", "гидроизоляц", "кровл", "пол"]):
            label = "AMBIGUOUS"
            reason = "Generic term 'устройство' without specific product context"
            ambs_picked += 1

    if label:
        r_entry = dict(r)
        r_entry["cohort"] = "NEGATIVE_AMBIGUOUS_CHALLENGE"
        r_entry["gold_label"] = label
        r_entry["gold_reason"] = reason
        cohort_C_ids.append(r_entry)
        selected_ids.add(r["id"])
        procurement_counts[pid] = procurement_counts.get(pid, 0) + 1
        if len(cohort_C_ids) >= 10:
            break

print(f"Cohort C selected: {len(cohort_C_ids)} rows ({negs_picked} CLEAR_NEGATIVE, {ambs_picked} AMBIGUOUS)")

total_holdout = cohort_A + cohort_B_ids + cohort_C_ids
print(f"TOTAL HOLDOUT SIZE: {len(total_holdout)} (Cohort A: {len(cohort_A)}, Cohort B: {len(cohort_B_ids)}, Cohort C: {len(cohort_C_ids)})")

# ==============================================================================
# 4. MANIFEST HASHING & FREEZING
# ==============================================================================
manifest_records = []
for r in total_holdout:
    ctx_hash = hashlib.sha256(r["context_block"].encode("utf-8")).hexdigest()
    rec = {
        "detail_id": r["id"],
        "procurement_id": r["procurement_id"],
        "document_name": r["document_name"],
        "category_code": r["category_code"],
        "category_name": r["category_name"],
        "subcategory_code": r["subcategory_code"],
        "subcategory_name": r["subcategory_name"],
        "matched_term": r["matched_term"],
        "match_method": r["match_method"] or "UNKNOWN",
        "score": float(r["score"]) if r["score"] is not None else 0.0,
        "matched_line": r.get("matched_line", ""),
        "context_before": r.get("context_before") or [],
        "context_after": r.get("context_after") or [],
        "context_block": r["context_block"],
        "context_block_sha256": ctx_hash,
        "cohort": r["cohort"],
        "gold_label": r["gold_label"],
        "gold_reason": r["gold_reason"],
    }
    manifest_records.append(rec)

manifest_str = json.dumps(manifest_records, ensure_ascii=False, sort_keys=True, indent=2)
manifest_sha256 = hashlib.sha256(manifest_str.encode("utf-8")).hexdigest()

manifest_data = {
    "manifest_sha256": manifest_sha256,
    "gold_frozen_before_model": True,
    "total_count": len(manifest_records),
    "records": manifest_records,
}

manifest_path = "/tmp/r3_4f_holdout_manifest.json"
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest_data, f, ensure_ascii=False, indent=2)

print("=" * 60)
print(f"MANIFEST SAVED TO {manifest_path}")
print(f"MANIFEST_SHA256={manifest_sha256}")
print(f"GOLD_FROZEN_BEFORE_MODEL=YES")
print("=" * 60)

crm_conn.close()
doc_conn.close()
