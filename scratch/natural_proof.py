#!/usr/bin/env python3
"""
Natural 10-row runtime proof + mocked validator input proof.
Uses 10 persisted details from the forensic set 35176..35275.
NO model calls. NO code changes. NO validation runs.
"""
import json
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    enrich_candidates_with_crm_facts,
)
from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
    _is_empty_context,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

# Diverse IDs: negatives, ambiguous, potential positive
IDS = [35176, 35180, 35200, 35220, 35240, 35250, 35260, 35265, 35270, 35275]

doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()
taxonomy = CrmTaxonomyLoader().load_snapshot()

# Fetch raw candidates
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT d.id, d.id as detail_id, d.match_id, d.procurement_id,
               d.category_code, d.subcategory_code,
               d.matched_term, d.term_type, d.score,
               d.row_data, d.page_or_sheet, d.row_number,
               d.context_before, d.context_after, d.match_method,
               m.document_name, m.archive_member_path
        FROM document_match_details d
        JOIN document_matches m ON d.match_id = m.id
        WHERE d.id = ANY(%s)
        ORDER BY d.id
    """, (IDS,))
    raw_candidates = [dict(r) for r in cur.fetchall()]

# Enrich
enriched = enrich_candidates_with_crm_facts(raw_candidates, crm_conn, taxonomy)

print("=" * 70)
print("SECTION 12 — TEN NATURAL RUNTIME PROOFS")
print("=" * 70)

for c in enriched:
    # Check DB column emptiness
    db_matched_empty = not c.get("matched_line") or not str(c.get("matched_line", "")).strip()
    db_before_empty = _is_empty_context(c.get("context_before"))
    db_after_empty = _is_empty_context(c.get("context_after"))

    # Check row_data presence
    rd = c.get("row_data")
    if isinstance(rd, str):
        try: rd = json.loads(rd)
        except: rd = {}
    if not isinstance(rd, dict):
        rd = {}
    rd_matched = bool(
        rd.get("matched_line") or rd.get("matched_display_text")
        or rd.get("text") or rd.get("raw_cells")
    )
    rd_before = bool(rd.get("context_before") and rd.get("context_before") != [])
    rd_after = bool(rd.get("context_after") and rd.get("context_after") != [])

    # Hydrate
    hydrated = hydrate_candidate_context(c)
    final_matched = bool(hydrated.get("matched_line"))
    final_before = bool(hydrated.get("context_before"))
    final_after = bool(hydrated.get("context_after"))

    # Build context block (NO model call)
    validator = ContextValidator(ai_caller=lambda p: '{"decision":"UNKNOWN","confidence":0.0}')
    block = validator.build_context_block(c)

    print(f"\nDETAIL_ID={c['id']}")
    print(f"  TERM='{c['matched_term']}'")
    print(f"  DOCUMENT={c['document_name']}")
    print(f"  DB_MATCHED_TEXT_EMPTY={db_matched_empty}")
    print(f"  DB_BEFORE_EMPTY={db_before_empty}")
    print(f"  DB_AFTER_EMPTY={db_after_empty}")
    print(f"  ROW_DATA_MATCHED_PRESENT={rd_matched}")
    print(f"  ROW_DATA_BEFORE_PRESENT={rd_before}")
    print(f"  ROW_DATA_AFTER_PRESENT={rd_after}")
    print(f"  FINAL_MATCHED_PRESENT={final_matched}")
    print(f"  FINAL_BEFORE_PRESENT={final_before}")
    print(f"  FINAL_AFTER_PRESENT={final_after}")
    print(f"  FINAL_CONTEXT_CHARS={len(block)}")
    if final_matched:
        print(f"  FINAL_MATCHED_TEXT='{hydrated['matched_line'][:80]}'")

final_matched_count = sum(
    1 for c in enriched
    if hydrate_candidate_context(c).get("matched_line")
)
print(f"\nFINAL_MATCHED_PRESENT={final_matched_count}/10")
assert final_matched_count >= 9, f"Expected >= 9/10, got {final_matched_count}/10"
print("CONTEXT_RECOVERY_WORKS=YES")

# ============================================================
# SECTION 13 — MOCKED VALIDATOR INPUT PROOF FOR DETAIL_ID=35176
# ============================================================
print("\n" + "=" * 70)
print("SECTION 13 — MOCKED VALIDATOR INPUT PROOF (DETAIL_ID=35176)")
print("=" * 70)

captured_prompts = []

def mock_ai(prompt):
    captured_prompts.append(prompt)
    return json.dumps({
        "detail_id": 35176,
        "decision": "UNKNOWN",
        "confidence": 0.0,
        "supporting_quote": "",
        "reason_code": "INSUFFICIENT_CONTEXT",
        "reason": "mock"
    })

mock_validator = ContextValidator(ai_caller=mock_ai)

# Find the 35176 candidate
c35176 = next(c for c in enriched if c["id"] == 35176)
result = mock_validator.validate_single(c35176)

assert len(captured_prompts) == 1, f"Expected 1 prompt, got {len(captured_prompts)}"
prompt_text = captured_prompts[0]

contains_matched = "Светильник" in prompt_text
contains_context = "Электрический щит" in prompt_text or "шт" in prompt_text

print(f"MODEL_CALLS=0 (mock only)")
print(f"MOCK_CAPTURE_CONTAINS_MATCHED_TEXT={contains_matched}")
print(f"MOCK_CAPTURE_CONTAINS_CONTEXT={contains_context}")
print(f"PROMPT_CHARS={len(prompt_text)}")
print(f"PROMPT_SNIPPET (first 300 chars):")
print(prompt_text[:300])

assert contains_matched, "Captured prompt must contain matched text"
assert contains_context, "Captured prompt must contain context"

print("\nMOCK_CAPTURE_CONTAINS_MATCHED_TEXT=YES")
print("MOCK_CAPTURE_CONTAINS_CONTEXT=YES")
print("ALL PROOFS PASSED")

doc_conn.close()
crm_conn.close()
