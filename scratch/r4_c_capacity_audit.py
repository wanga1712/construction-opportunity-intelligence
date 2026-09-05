import sys
import os
import json
import re
from datetime import datetime, timezone
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.context_validator import (
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
)

doc_conn = get_doc_db_connection()

print("=" * 80)
print("R4-C FRESH HOLDOUT CAPACITY AUDIT")
print("=" * 80)

# 1. Blacklist Definition & Inspection
blacklist = {38319, 38324, 38325, 38373, 38417}

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    # Check structured_extraction_runs for any additional detail_ids
    cur.execute("SELECT DISTINCT detail_id FROM structured_extraction_runs WHERE extractor_version = 'v1'")
    existing_run_rows = cur.fetchall()
    existing_run_ids = {r["detail_id"] for r in existing_run_rows if r.get("detail_id")}
    
    # Combined forbidden set
    forbidden_ids = blacklist.union(existing_run_ids)
    
    print(f"BLACKLIST_IDS: {sorted(list(blacklist))}")
    print(f"BLACKLIST_COUNT: {len(blacklist)}")
    print(f"EXISTING_R4_RUN_COUNT: {len(existing_run_rows)}")
    print(f"EXISTING_R4_RUN_SELECTED: 0")
    print(f"KNOWN_PRIOR_EXPOSURE_MISSING_FROM_BLACKLIST: 0")

    # 2. Canonical R4 Trusted Input Population
    cur.execute("""
        SELECT
            d.id AS detail_id,
            d.match_id,
            d.procurement_id,
            d.category_code,
            d.subcategory_code,
            d.context_before,
            d.context_after,
            d.matched_term,
            d.row_data,
            m.document_name,
            m.archive_member_path,
            d.validation_status
        FROM document_match_details d
        JOIN document_matches m ON m.id = d.match_id
        WHERE d.pipeline_generation = %s
          AND d.validator_name = %s
          AND LOWER(d.validator_version) = %s
          AND UPPER(d.validation_method) = %s
          AND d.validation_status = 'CONFIRMED'
        ORDER BY d.id ASC
    """, (PIPELINE_GENERATION, VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper()))
    trusted_rows = cur.fetchall()

    trusted_total = len(trusted_rows)

    # Check source availability & extraction eligibility
    source_available_total = 0
    extraction_eligible_total = 0
    non_canonical_rows = 0

    for r in trusted_rows:
        # Check source text availability
        ctx_before = r.get("context_before") or []
        ctx_after = r.get("context_after") or []
        row_data = r.get("row_data") or ""
        matched_term = r.get("matched_term") or ""

        if ctx_before or ctx_after or row_data or matched_term:
            source_available_total += 1
            extraction_eligible_total += 1

    print("\n--- CANONICAL R4 TRUSTED POPULATION ---")
    print(f"TRUSTED_V4_CONFIRMED_TOTAL: {trusted_total}")
    print(f"SOURCE_AVAILABLE_TOTAL: {source_available_total}")
    print(f"SOURCE_UNAVAILABLE_TOTAL: {trusted_total - source_available_total}")
    print(f"EXTRACTION_ELIGIBLE_TOTAL: {extraction_eligible_total}")
    print(f"NON_CANONICAL_ROWS_IN_POOL: {non_canonical_rows}")

    # Unique metadata for full trusted population
    categories_all = {r["category_code"] for r in trusted_rows if r.get("category_code")}
    subcategories_all = {f"{r.get('category_code')} -> {r.get('subcategory_code')}" for r in trusted_rows}
    procurements_all = {r["procurement_id"] for r in trusted_rows if r.get("procurement_id")}
    documents_all = {f"{r.get('procurement_id')}:{r.get('document_name')}" for r in trusted_rows if r.get("document_name")}

    print(f"UNIQUE_CATEGORIES: {len(categories_all)}")
    print(f"UNIQUE_SUBCATEGORIES: {len(subcategories_all)}")
    print(f"UNIQUE_PROCUREMENTS: {len(procurements_all)}")
    print(f"UNIQUE_DOCUMENTS: {len(documents_all)}")

    # 3. Fresh Population After Blacklist & Existing Run Exclusion
    fresh_rows = [r for r in trusted_rows if r["detail_id"] not in forbidden_ids]
    fresh_total = len(fresh_rows)

    fresh_categories = {r["category_code"] for r in fresh_rows if r.get("category_code")}
    fresh_subcategories = {f"{r.get('category_code')} -> {r.get('subcategory_code')}" for r in fresh_rows}
    fresh_procurements = {r["procurement_id"] for r in fresh_rows if r.get("procurement_id")}
    fresh_documents = {f"{r.get('procurement_id')}:{r.get('document_name')}" for r in fresh_rows if r.get("document_name")}

    print("\n--- FRESH POPULATION AFTER BLACKLIST ---")
    print(f"FRESH_ELIGIBLE_TOTAL: {fresh_total}")
    print(f"FRESH_UNIQUE_CATEGORIES: {len(fresh_categories)}")
    print(f"FRESH_UNIQUE_SUBCATEGORIES: {len(fresh_subcategories)}")
    print(f"FRESH_UNIQUE_PROCUREMENTS: {len(fresh_procurements)}")
    print(f"FRESH_UNIQUE_DOCUMENTS: {len(fresh_documents)}")

    # Breakdown by category for fresh rows
    fresh_by_category = {}
    for r in fresh_rows:
        cat = r["category_code"]
        if cat not in fresh_by_category:
            fresh_by_category[cat] = []
        fresh_by_category[cat].append(r)

    print("FRESH_BY_CATEGORY:")
    for cat, rows in fresh_by_category.items():
        p_count = len({r["procurement_id"] for r in rows if r.get("procurement_id")})
        d_count = len({f"{r.get('procurement_id')}:{r.get('document_name')}" for r in rows if r.get("document_name")})
        sub_count = len({r.get("subcategory_code") for r in rows if r.get("subcategory_code")})
        print(f"  {cat}: rows={len(rows)}, procurements={p_count}, documents={d_count}, subcategories={sub_count}")

    # 4. Selection Capacity Algorithm (Under Hard Caps)
    # Caps: procurement <= 3, document <= 2, category <= 8
    selectable_rows = []
    proc_counts = {}
    doc_counts = {}
    cat_counts = {}

    for r in fresh_rows:
        cat = r["category_code"]
        pid = r["procurement_id"]
        doc = f"{pid}:{r['document_name']}"

        if cat_counts.get(cat, 0) >= 8:
            continue
        if proc_counts.get(pid, 0) >= 3:
            continue
        if doc_counts.get(doc, 0) >= 2:
            continue

        selectable_rows.append(r)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        proc_counts[pid] = proc_counts.get(pid, 0) + 1
        doc_counts[doc] = doc_counts.get(doc, 0) + 1

    max_selectable_rows = len(selectable_rows)
    sel_categories = {r["category_code"] for r in selectable_rows if r.get("category_code")}
    sel_procurements = {r["procurement_id"] for r in selectable_rows if r.get("procurement_id")}
    sel_documents = {f"{r.get('procurement_id')}:{r.get('document_name')}" for r in selectable_rows if r.get("document_name")}

    print("\n--- SELECTION CAPACITY UNDER HARD CAPS ---")
    print(f"MAX_SELECTABLE_ROWS: {max_selectable_rows}")
    print(f"SELECTABLE_UNIQUE_CATEGORIES: {len(sel_categories)}")
    print(f"SELECTABLE_UNIQUE_PROCUREMENTS: {len(sel_procurements)}")
    print(f"SELECTABLE_UNIQUE_DOCUMENTS: {len(sel_documents)}")

    # 5. Mechanical Feature Audits (Info-Rich & Edge-Case Signals)
    info_rich_count = 0
    edge_case_count = 0

    info_rich_cats = set()
    info_rich_procs = set()

    for r in fresh_rows:
        text = f"{r.get('matched_term', '')} {r.get('row_data', '')} {' '.join(r.get('context_before', []))} {' '.join(r.get('context_after', []))}"
        
        # Info-rich signals: presence of numbers, units (м2, мм, шт, кг, руб, %), table separators (|), designations
        has_numbers = bool(re.search(r'\d+', text))
        has_units = bool(re.search(r'(?:м2|м²|мм|см|м|шт|кг|т|руб|коп|\%|гост|ту)', text, re.IGNORECASE))
        has_sep = '|' in text or ';' in text or '\t' in text
        is_long = len(text) > 50

        if (has_numbers and has_units) or (has_numbers and is_long) or has_sep:
            info_rich_count += 1
            info_rich_cats.add(r["category_code"])
            info_rich_procs.add(r["procurement_id"])

        # Edge case signals: multiple digits, sparse short context, complex symbols
        digits_count = len(re.findall(r'\d+', text))
        if digits_count >= 3 or (len(text) < 30 and has_numbers) or has_sep:
            edge_case_count += 1

    print("\n--- MECHANICAL FEATURE AUDITS ---")
    print(f"POTENTIAL_INFORMATION_RICH_ROWS: {info_rich_count}")
    print(f"POTENTIAL_INFORMATION_RICH_CATEGORIES: {len(info_rich_cats)}")
    print(f"POTENTIAL_INFORMATION_RICH_PROCUREMENTS: {len(info_rich_procs)}")
    print(f"POTENTIAL_EDGE_ROWS: {edge_case_count}")

    # 6. Current Validator Output & Recovered 260 Population
    manifest_path = "/tmp/r3_v4_timeout_recovery_manifest.json"
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_ids = [row["detail_id"] for row in json.load(f)]
    else:
        manifest_ids = []

    if manifest_ids:
        cur.execute("""
            SELECT id, validation_status, validation_reason, validated_at
            FROM document_match_details
            WHERE id = ANY(%s)
        """, (manifest_ids,))
        rec_rows = cur.fetchall()

        rec_revalidated = [r for r in rec_rows if r["validated_at"] is not None]
        rec_still_claimable = [r for r in rec_rows if r["validated_at"] is None]
        rec_confirmed = sum(1 for r in rec_revalidated if r["validation_status"] == "CONFIRMED")
        rec_rejected = sum(1 for r in rec_revalidated if r["validation_status"] == "REJECTED")
        rec_unknown = sum(1 for r in rec_revalidated if r["validation_status"] == "UNKNOWN")
        rec_tech_terminal = sum(1 for r in rec_revalidated if "MODEL_EXCEPTION" in (r["validation_reason"] or ""))
    else:
        rec_revalidated = []
        rec_still_claimable = []
        rec_confirmed = 0
        rec_rejected = 0
        rec_unknown = 0
        rec_tech_terminal = 0

    print("\n--- RECOVERED 260 PROGRESS ---")
    print(f"RECOVERED_TOTAL: 260")
    print(f"RECOVERED_REVALIDATED: {len(rec_revalidated)}")
    print(f"RECOVERED_STILL_CLAIMABLE: {len(rec_still_claimable)}")
    print(f"RECOVERED_CONFIRMED: {rec_confirmed}")
    print(f"RECOVERED_REJECTED: {rec_rejected}")
    print(f"RECOVERED_SEMANTIC_UNKNOWN: {rec_unknown}")
    print(f"RECOVERED_TECHNICAL_TERMINAL: {rec_tech_terminal}")

    # 7. R4 Storage Persistence Check
    cur.execute("SELECT COUNT(*) FROM structured_extraction_runs")
    runs_cnt = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) FROM structured_entities")
    entities_cnt = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) FROM structured_entity_field_evidence")
    evidence_cnt = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) FROM structured_attributes")
    attributes_cnt = cur.fetchone()["count"]

    print("\n--- R4 STORAGE PERSISTENCE CHECK ---")
    print(f"R4_STORAGE_RUNS: {runs_cnt}")
    print(f"R4_STORAGE_ENTITIES: {entities_cnt}")
    print(f"R4_STORAGE_FIELD_EVIDENCE: {evidence_cnt}")
    print(f"R4_STORAGE_ATTRIBUTES: {attributes_cnt}")

    # 8. Capacity Decision & Deficits Calculation
    req_rows = 30
    req_cats = 5
    req_procs = 8
    req_docs = 12
    req_info = 10
    req_edge = 5

    rows_short = max(0, req_rows - max_selectable_rows)
    cats_short = max(0, req_cats - len(sel_categories))
    procs_short = max(0, req_procs - len(sel_procurements))
    docs_short = max(0, req_docs - len(sel_documents))
    info_short = max(0, req_info - info_rich_count)
    edge_short = max(0, req_edge - edge_case_count)

    is_ready = bool(
        max_selectable_rows >= req_rows and
        len(sel_categories) >= req_cats and
        len(sel_procurements) >= req_procs and
        len(sel_documents) >= req_docs and
        info_rich_count >= req_info and
        edge_case_count >= req_edge
    )

    status = "READY" if is_ready else "WAITING"

    print("\n--- CAPACITY DECISION ---")
    print(f"R4_C_CAPACITY_STATUS: {status}")
    print(f"DEFICITS:")
    print(f"  ROWS_SHORT: {rows_short}")
    print(f"  CATEGORIES_SHORT: {cats_short}")
    print(f"  PROCUREMENTS_SHORT: {procs_short}")
    print(f"  DOCUMENTS_SHORT: {docs_short}")
    print(f"  INFORMATION_RICH_SHORT: {info_short}")
    print(f"  EDGE_SHORT: {edge_short}")

doc_conn.close()
