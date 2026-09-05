import sys
import os
import json
import re
import hashlib
from datetime import datetime, timezone, timedelta
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    get_cached_target_procurement_ids,
)
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    SYSTEM_PROMPT,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    PROMPT_VERSION,
)
from tender_documents_research.document_processor.r4_input_selector import (
    build_source_document_context,
)

class CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

priors = load_okpd_priors_from_db(CrmDbWrapper(crm_conn))
target_pids = set(get_cached_target_procurement_ids(crm_conn, priors))

validator = ContextValidator()

# 1. Backlog Check
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.id AS detail_id, d.procurement_id
        FROM document_match_details d
        WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.validated_at IS NULL
          AND (d.validation_status IS NULL OR d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING'))
    """)
    unval_rows = [r for r in cur.fetchall() if r["procurement_id"] in target_pids]

target_unval_total = len(unval_rows)

# 2. Terminal V4 Rows Query
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT
            d.*,
            m.queue_id
        FROM document_match_details d
        JOIN document_matches m ON m.id = d.match_id
        WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
          AND d.validator_name = 'context_validator'
          AND LOWER(d.validator_version) = 'v4'
          AND UPPER(d.validation_method) = 'QWEN_CONTEXT_V4'
          AND d.validation_status IN ('CONFIRMED', 'REJECTED', 'UNKNOWN')
        ORDER BY d.validated_at DESC
    """)
    all_v4_terminal = [dict(r) for r in cur.fetchall()]

# Rename d.id to detail_id for consistency
for r in all_v4_terminal:
    r["detail_id"] = r["id"]

# Forensic window: exact recent 260 rows (or all if < 260)
forensic_260 = all_v4_terminal[:260]

print("=" * 80)
print("CRM-V3-RUNTIME-V4-UNKNOWN-COLLAPSE-FORENSIC REPORT")
print("=" * 80)
print(f"TARGET_UNVALIDATED_TOTAL: {target_unval_total}")
print(f"ALL_V4_TERMINAL_TOTAL: {len(all_v4_terminal)}")
print(f"FORENSIC_ROWS_COUNT: {len(forensic_260)}")

f_confirmed = sum(1 for r in forensic_260 if r["validation_status"] == "CONFIRMED")
f_rejected = sum(1 for r in forensic_260 if r["validation_status"] == "REJECTED")
f_unknown = sum(1 for r in forensic_260 if r["validation_status"] == "UNKNOWN")
print(f"FORENSIC_CONFIRMED: {f_confirmed}")
print(f"FORENSIC_REJECTED: {f_rejected}")
print(f"FORENSIC_UNKNOWN: {f_unknown}")

start_val_at = forensic_260[-1]["validated_at"] if forensic_260 else None
end_val_at = forensic_260[0]["validated_at"] if forensic_260 else None
print(f"START_VALIDATED_AT: {start_val_at}")
print(f"END_VALIDATED_AT: {end_val_at}")

# 3. Distribution by Category / Subcategory / Procurement / Document
f_cats = set(r["category_code"] for r in forensic_260)
f_subcats = set(f"{r['category_code']} -> {r.get('subcategory_code')}" for r in forensic_260)
f_procs = set(r["procurement_id"] for r in forensic_260)
f_docs = set(r["queue_id"] for r in forensic_260 if r.get("queue_id"))

by_cat = {}
by_subcat = {}
by_proc = {}
by_doc = {}

for r in forensic_260:
    cat = r["category_code"]
    subcat = f"{cat} -> {r.get('subcategory_code')}"
    proc = r["procurement_id"]
    doc = r.get("queue_id")
    
    by_cat[cat] = by_cat.get(cat, 0) + 1
    by_subcat[subcat] = by_subcat.get(subcat, 0) + 1
    by_proc[proc] = by_proc.get(proc, 0) + 1
    if doc: by_doc[doc] = by_doc.get(doc, 0) + 1

print("\n--- DISTRIBUTION ---")
print(f"UNIQUE_CATEGORIES: {len(f_cats)}")
print(f"UNIQUE_SUBCATEGORIES: {len(f_subcats)}")
print(f"UNIQUE_PROCUREMENTS: {len(f_procs)}")
print(f"UNIQUE_DOCUMENTS: {len(f_docs)}")
print(f"BY_CATEGORY: {by_cat}")
print(f"BY_SUBCATEGORY: {by_subcat}")

# 4. Validation Reason Distribution
reasons_dist = {}
reason_codes_dist = {}
for r in forensic_260:
    reas = r.get("validation_reason") or "UNKNOWN_REASON"
    reasons_dist[reas] = reasons_dist.get(reas, 0) + 1
    
    m = re.match(r"^\[([A-Z0-9_]+)\]", reas)
    code = m.group(1) if m else "NO_CODE"
    reason_codes_dist[code] = reason_codes_dist.get(code, 0) + 1

print("\n--- REASON DISTRIBUTION ---")
print(f"REASON_CODES: {reason_codes_dist}")
print(f"TOP_REASONS: {json.dumps(dict(sorted(reasons_dist.items(), key=lambda x: x[1], reverse=True)[:10]), indent=2, ensure_ascii=False)}")

# 5. Source Context Health & Hydration (Reconstruct visible source)
context_lengths = []
empty_sources = 0
tiny_sources = 0
lt_200_sources = 0
between_200_1000 = 0
gt_1000_sources = 0

q_section_missing = 0
doc_section_missing = 0
marker_leaks = 0
matched_term_in_source = 0
matched_term_not_in_source = 0

for r in forensic_260:
    cand = {
        "procurement_id": r["procurement_id"],
        "category_code": r["category_code"],
        "matched_term": r.get("matched_term"),
        "context_before": r.get("context_before"),
        "context_after": r.get("context_after"),
        "row_data": r.get("row_data"),
    }

    vis_source = build_source_document_context(cand)
    l = len(vis_source)
    context_lengths.append(l)

    if l == 0: empty_sources += 1
    elif l < 50: tiny_sources += 1
    
    if l < 200: lt_200_sources += 1
    elif 200 <= l <= 1000: between_200_1000 += 1
    else: gt_1000_sources += 1

    prompt_str = validator.build_prompt(r["category_code"], r.get("subcategory_code"), vis_source)
    if "QUESTION BLOCK:" not in prompt_str: q_section_missing += 1
    if "DOCUMENT CONTEXT:" not in prompt_str: doc_section_missing += 1
    if "TRUNCATED_MARKER" in vis_source: marker_leaks += 1

    m_term = (r.get("matched_term") or "").strip().lower()
    if m_term and m_term in vis_source.lower():
        matched_term_in_source += 1
    else:
        matched_term_not_in_source += 1

context_lengths.sort()
min_len = context_lengths[0] if context_lengths else 0
max_len = context_lengths[-1] if context_lengths else 0
mean_len = round(sum(context_lengths) / len(context_lengths), 1) if context_lengths else 0.0
p50_len = context_lengths[len(context_lengths)//2] if context_lengths else 0
p95_len = context_lengths[int(len(context_lengths)*0.95)] if context_lengths else 0

print("\n--- SOURCE CONTEXT HEALTH ---")
print(f"VISIBLE_SOURCE_EMPTY: {empty_sources}")
print(f"ONLY_TINY_CONTEXT_LT_50: {tiny_sources}")
print(f"CONTEXT_LT_200: {lt_200_sources}")
print(f"CONTEXT_200_1000: {between_200_1000}")
print(f"CONTEXT_GT_1000: {gt_1000_sources}")
print(f"VISIBLE_SOURCE_LENGTH_MIN: {min_len}")
print(f"VISIBLE_SOURCE_LENGTH_MEAN: {mean_len}")
print(f"VISIBLE_SOURCE_LENGTH_P50: {p50_len}")
print(f"VISIBLE_SOURCE_LENGTH_P95: {p95_len}")
print(f"VISIBLE_SOURCE_LENGTH_MAX: {max_len}")
print(f"QUESTION_SECTION_MISSING: {q_section_missing}")
print(f"DOCUMENT_SECTION_MISSING: {doc_section_missing}")
print(f"MARKER_LEAKS: {marker_leaks}")
print(f"MATCHED_TERM_IN_VISIBLE_SOURCE: {matched_term_in_source}")
print(f"MATCHED_TERM_NOT_IN_VISIBLE_SOURCE: {matched_term_not_in_source}")

# 6. Queue Concentration
detail_ids = [r["detail_id"] for r in forensic_260]
min_id = min(detail_ids) if detail_ids else 0
max_id = max(detail_ids) if detail_ids else 0
range_span = (max_id - min_id + 1) if max_id >= min_id else 1
contiguity_ratio = round(len(detail_ids) / range_span, 4)

top_proc_share = round(max(by_proc.values()) / len(forensic_260), 4) if forensic_260 else 0.0
top_doc_share = round(max(by_doc.values()) / len(forensic_260), 4) if (forensic_260 and by_doc) else 0.0
top_cat_share = round(max(by_cat.values()) / len(forensic_260), 4) if forensic_260 else 0.0

is_pathological_block = bool(top_cat_share >= 0.80 or top_proc_share >= 0.80 or top_doc_share >= 0.80)

print("\n--- QUEUE CONCENTRATION ---")
print(f"MIN_DETAIL_ID: {min_id}")
print(f"MAX_DETAIL_ID: {max_id}")
print(f"CONTIGUITY_RATIO: {contiguity_ratio}")
print(f"TOP_PROCUREMENT_SHARE: {top_proc_share}")
print(f"TOP_DOCUMENT_SHARE: {top_doc_share}")
print(f"TOP_CATEGORY_SHARE: {top_cat_share}")
print(f"PATHOLOGICAL_BLOCK: {is_pathological_block}")

# 7. Compare Early Good Production Window vs Recent 260
early_v4_rows = all_v4_terminal[260:] if len(all_v4_terminal) > 260 else []
early_confirmed = sum(1 for r in early_v4_rows if r["validation_status"] == "CONFIRMED")
early_rejected = sum(1 for r in early_v4_rows if r["validation_status"] == "REJECTED")
early_unknown = sum(1 for r in early_v4_rows if r["validation_status"] == "UNKNOWN")

early_reasons_dist = {}
for r in early_v4_rows:
    reas = r.get("validation_reason") or "UNKNOWN_REASON"
    m = re.match(r"^\[([A-Z0-9_]+)\]", reas)
    code = m.group(1) if m else "NO_CODE"
    early_reasons_dist[code] = early_reasons_dist.get(code, 0) + 1

early_cat_dist = {}
for r in early_v4_rows:
    cat = r["category_code"]
    early_cat_dist[cat] = early_cat_dist.get(cat, 0) + 1

print("\n--- EARLY PRODUCTION WINDOW COMPARISON ---")
print(f"EARLY_ROWS_COUNT: {len(early_v4_rows)}")
print(f"EARLY_CONFIRMED: {early_confirmed}")
print(f"EARLY_REJECTED: {early_rejected}")
print(f"EARLY_UNKNOWN: {early_unknown}")
print(f"EARLY_REASONS: {early_reasons_dist}")
print(f"EARLY_CATEGORIES: {early_cat_dist}")

# 8. Runtime & Import Tree Audit
import inspect
val_file = inspect.getfile(ContextValidator)
sys_prompt_sha256 = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()

print("\n--- RUNTIME CODE AUTHORITY ---")
print(f"VALIDATOR_FILE: {val_file}")
print(f"VALIDATOR_NAME: {VALIDATOR_NAME}")
print(f"VALIDATOR_VERSION: {VALIDATOR_VERSION}")
print(f"VALIDATION_METHOD: {VALIDATION_METHOD}")
print(f"PROMPT_VERSION: {PROMPT_VERSION}")
print(f"CONFIRM_THRESHOLD: {DEFAULT_CONFIRM_THRESHOLD}")
print(f"REJECT_THRESHOLD: {DEFAULT_REJECT_THRESHOLD}")
print(f"SYSTEM_PROMPT_SHA256: {sys_prompt_sha256}")

doc_conn.close()
crm_conn.close()
