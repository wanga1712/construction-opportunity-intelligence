#!/usr/bin/env python3
"""
R3-4F-B-C Step 18: Real 55 Holdout Input Replay (No Model Calls) v5.
Reloads DB candidates for the 55 frozen detail_ids and builds ContextValidator v3 context payloads.
Validates:
- OVER_LIMIT = 0 (hard contract len <= 3000)
- QUESTION_PRESENT = 55
- DOCUMENT_SECTION_PRESENT = 55
- NEGATIVE_PHRASE_VISIBLE = 0
- GENERATED_MARKER_IN_VISIBLE_SOURCE = 0
"""
import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

manifest_path = "/tmp/r3_4f_holdout_manifest.json"
assert os.path.exists(manifest_path), f"Manifest file missing: {manifest_path}"

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_data = json.load(f)

records = manifest_data["records"]
detail_ids = [r["detail_id"] for r in records]

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
)
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
)

doc_conn = get_doc_db_connection()
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

doc_conn.close()

validator = ContextValidator(ai_caller=lambda p: "")

over_3000_count = 0
question_present_count = 0
doc_section_present_count = 0
neg_phrase_visible_count = 0
gen_marker_in_visible_source_count = 0

nonempty_source_matched_count = 0
full_matched_visible_count = 0
truncated_matched_count = 0
matched_term_source_count = 0
matched_term_visible_count = 0

generated_markers = [
    "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]",
    ">>> НАЙДЕННАЯ СТРОКА:",
    "...[контекст до совпадения сокращён]...",
    "...[контекст после совпадения сокращён]...",
    "...[строка совпадения сокращена]...",
]

for rec in records:
    db_c = db_rows_by_id.get(rec["detail_id"], rec)
    db_c["category_name"] = rec.get("category_name", db_c["category_code"])
    db_c["subcategory_name"] = rec.get("subcategory_name", db_c["subcategory_code"])
    db_c["procurement_title"] = rec.get("procurement_title", "")
    db_c["procurement_okpd_code"] = rec.get("procurement_okpd_code", "")
    db_c["procurement_okpd_name"] = rec.get("procurement_okpd_name", "")
    db_c["negative_phrases"] = rec.get("negative_phrases", [])

    payload = validator.build_context_payload(db_c)
    block = payload["context_block"]
    visible_source_text = payload["visible_source_text"]

    # 1. Hard 3000 limit check
    if len(block) > 3000:
        over_3000_count += 1

    # 2. Check structure
    if "[ВОПРОС]" in block:
        question_present_count += 1
    if "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" in block:
        doc_section_present_count += 1

    # 3. Check negative phrases
    neg_phrases = rec.get("negative_phrases") or []
    for np in neg_phrases:
        np_clean = str(np).strip()
        if np_clean and np_clean in block:
            neg_phrase_visible_count += 1
            break

    # 4. Check ZERO generated markers in visible_source_text
    for gm in generated_markers:
        if gm in visible_source_text:
            gen_marker_in_visible_source_count += 1
            break

    # 5. Check matched_line & matched_term
    c_hydrated = hydrate_candidate_context(db_c)
    src_m_line = c_hydrated.get("matched_line", "").strip()
    term = str(db_c.get("matched_term") or "").strip().lower()

    if src_m_line:
        nonempty_source_matched_count += 1
        if src_m_line in block:
            full_matched_visible_count += 1
        else:
            truncated_matched_count += 1
        
        if term and term in src_m_line.lower():
            matched_term_source_count += 1
            if term in block.lower():
                matched_term_visible_count += 1

print("=" * 60)
print("REAL 55 HOLDOUT INPUT REPLAY (NO MODEL CALLS) v5")
print(f"  ROWS={len(records)}")
print(f"  OVER_LIMIT={over_3000_count}")
print(f"  QUESTION_PRESENT={question_present_count}")
print(f"  DOCUMENT_SECTION_PRESENT={doc_section_present_count}")
print(f"  NEGATIVE_PHRASE_VISIBLE={neg_phrase_visible_count}")
print(f"  GENERATED_MARKER_IN_VISIBLE_SOURCE={gen_marker_in_visible_source_count}")
print(f"  NONEMPTY_SOURCE_MATCHED={nonempty_source_matched_count}")
print(f"  TRUNCATED_MATCHED={truncated_matched_count}")
print(f"  MATCHED_TERM_SOURCE_COUNT={matched_term_source_count}")
print(f"  MATCHED_TERM_VISIBLE_COUNT={matched_term_visible_count}")
print("=" * 60)
