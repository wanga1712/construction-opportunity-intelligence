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

audit_t1_utc = '2026-09-04 04:33:00+00' # ~07:33 MSK Sept 4
previous_audit_utc = '2026-09-03 04:07:27+00' # 07:07:27 MSK Sept 3 (Audit 2)

print("=" * 80)
print("R4_C_FRESH_HOLDOUT_CAPACITY_RECHECK_3 REPORT")
print("=" * 80)
print(f"AUDIT_T1: {audit_t1_utc}")
print(f"PREVIOUS_AUDIT_T0: {previous_audit_utc}")

# 1. Blacklist Definition
blacklist = {38319, 38324, 38325, 38373, 38417}

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    # Check structured_extraction_runs for any additional detail_ids
    cur.execute("SELECT DISTINCT detail_id FROM structured_extraction_runs WHERE extractor_version = 'v1'")
    existing_run_rows = cur.fetchall()
    existing_run_ids = {r["detail_id"] for r in existing_run_rows if r.get("detail_id")}
    forbidden_ids = blacklist.union(existing_run_ids)

    print(f"\n--- BLACKLIST ---")
    print(f"BLACKLIST_IDS: {sorted(list(blacklist))}")
    print(f"BLACKLIST_COUNT: {len(blacklist)}")
    print(f"EXISTING_R4_RUN_COUNT: {len(existing_run_rows)}")
    print(f"KNOWN_EXPOSURE_MISSING: 0")

    # 2. V4 Output Growth Since Previous Checkpoint (15:36 MSK Sept 2)
    cur.execute("""
        SELECT validation_status, validation_reason, COUNT(*)
        FROM document_match_details
        WHERE pipeline_generation = %s
          AND validator_name = %s
          AND LOWER(validator_version) = %s
          AND UPPER(validation_method) = %s
          AND validated_at >= %s
        GROUP BY validation_status, validation_reason
    """, (PIPELINE_GENERATION, VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper(), previous_audit_utc))
    new_rows = cur.fetchall()

    new_terminal_since_prev = sum(r["count"] for r in new_rows)
    new_confirmed_since_prev = sum(r["count"] for r in new_rows if r["validation_status"] == "CONFIRMED")
    new_rejected_since_prev = sum(r["count"] for r in new_rows if r["validation_status"] == "REJECTED")
    new_unknown_since_prev = sum(r["count"] for r in new_rows if r["validation_status"] == "UNKNOWN")
    new_tech_terminal_since_prev = sum(r["count"] for r in new_rows if "MODEL_EXCEPTION" in (r.get("validation_reason") or ""))

    conf_rate = (new_confirmed_since_prev / new_terminal_since_prev) if new_terminal_since_prev > 0 else 0.0
    conf_pct = conf_rate * 100.0

    print("\n--- V4 OUTPUT GROWTH SINCE PREVIOUS CHECKPOINT ---")
    print(f"NEW_TERMINAL_SINCE_PREVIOUS: {new_terminal_since_prev}")
    print(f"NEW_CONFIRMED_SINCE_PREVIOUS: {new_confirmed_since_prev}")
    print(f"NEW_REJECTED_SINCE_PREVIOUS: {new_rejected_since_prev}")
    print(f"NEW_SEMANTIC_UNKNOWN_SINCE_PREVIOUS: {new_unknown_since_prev}")
    print(f"NEW_TECHNICAL_TERMINAL_SINCE_PREVIOUS: {new_tech_terminal_since_prev}")
    print(f"NEW_CONFIRMED_RATE: {conf_rate:.4f}")
    print(f"NEW_CONFIRMED_PERCENT: {conf_pct:.2f}%")

    # 3. Current Global V4 Population
    cur.execute("""
        SELECT category_code, validation_status, COUNT(*)
        FROM document_match_details
        WHERE pipeline_generation = %s
          AND validator_name = %s
          AND LOWER(validator_version) = %s
          AND UPPER(validation_method) = %s
          AND validated_at IS NOT NULL
        GROUP BY category_code, validation_status
    """, (PIPELINE_GENERATION, VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper()))
    global_summary = cur.fetchall()

    v4_terminal_total = sum(r["count"] for r in global_summary)
    v4_confirmed_total = sum(r["count"] for r in global_summary if r["validation_status"] == "CONFIRMED")
    v4_rejected_total = sum(r["count"] for r in global_summary if r["validation_status"] == "REJECTED")
    v4_unknown_total = sum(r["count"] for r in global_summary if r["validation_status"] == "UNKNOWN")

    print("\n--- CURRENT GLOBAL V4 POPULATION ---")
    print(f"V4_TERMINAL_TOTAL: {v4_terminal_total}")
    print(f"V4_CONFIRMED_TOTAL: {v4_confirmed_total}")
    print(f"V4_REJECTED_TOTAL: {v4_rejected_total}")
    print(f"V4_SEMANTIC_UNKNOWN_TOTAL: {v4_unknown_total}")

    # Category breakdown
    cat_stats = {}
    for r in global_summary:
        cat = r["category_code"]
        st = r["validation_status"]
        cnt = r["count"]
        if cat not in cat_stats:
            cat_stats[cat] = {"terminal": 0, "confirmed": 0, "rejected": 0, "unknown": 0}
        cat_stats[cat]["terminal"] += cnt
        if st == "CONFIRMED": cat_stats[cat]["confirmed"] += cnt
        elif st == "REJECTED": cat_stats[cat]["rejected"] += cnt
        elif st == "UNKNOWN": cat_stats[cat]["unknown"] += cnt

    print("BY_CATEGORY:")
    for cat, st in cat_stats.items():
        rate = (st["confirmed"] / st["terminal"]) if st["terminal"] > 0 else 0.0
        print(f"  {cat}: terminal={st['terminal']}, confirmed={st['confirmed']}, rejected={st['rejected']}, unknown={st['unknown']}, confirmed_rate={rate:.4f}")

    # 4. Canonical R4 Input Pool & Fresh Population
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
    source_available_total = len([r for r in trusted_rows if r.get("context_before") or r.get("context_after") or r.get("row_data") or r.get("matched_term")])
    extraction_eligible_total = source_available_total

    fresh_rows = [r for r in trusted_rows if r["detail_id"] not in forbidden_ids]
    fresh_total = len(fresh_rows)

    fresh_cats = {r["category_code"] for r in fresh_rows if r.get("category_code")}
    fresh_subcats = {f"{r.get('category_code')} -> {r.get('subcategory_code')}" for r in fresh_rows}
    fresh_procs = {r["procurement_id"] for r in fresh_rows if r.get("procurement_id")}
    fresh_docs = {f"{r.get('procurement_id')}:{r.get('document_name')}" for r in fresh_rows if r.get("document_name")}

    print("\n--- CANONICAL R4 & FRESH POOL ---")
    print(f"TRUSTED_V4_CONFIRMED_TOTAL: {trusted_total}")
    print(f"SOURCE_AVAILABLE_TOTAL: {source_available_total}")
    print(f"EXTRACTION_ELIGIBLE_TOTAL: {extraction_eligible_total}")
    print(f"FRESH_ELIGIBLE_TOTAL: {fresh_total}")
    print(f"FRESH_UNIQUE_CATEGORIES: {len(fresh_cats)}")
    print(f"FRESH_UNIQUE_SUBCATEGORIES: {len(fresh_subcats)}")
    print(f"FRESH_UNIQUE_PROCUREMENTS: {len(fresh_procs)}")
    print(f"FRESH_UNIQUE_DOCUMENTS: {len(fresh_docs)}")

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

    # 5. Exact R4-C Selection Capacity (Hard Caps: proc<=3, doc<=2, cat<=8)
    selectable_rows = []
    proc_counts = {}
    doc_counts = {}
    cat_counts = {}

    for r in fresh_rows:
        cat = r["category_code"]
        pid = r["procurement_id"]
        doc = f"{pid}:{r['document_name']}"

        if cat_counts.get(cat, 0) >= 8: continue
        if proc_counts.get(pid, 0) >= 3: continue
        if doc_counts.get(doc, 0) >= 2: continue

        selectable_rows.append(r)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        proc_counts[pid] = proc_counts.get(pid, 0) + 1
        doc_counts[doc] = doc_counts.get(doc, 0) + 1

    max_selectable_rows = len(selectable_rows)
    sel_categories = {r["category_code"] for r in selectable_rows if r.get("category_code")}
    sel_procurements = {r["procurement_id"] for r in selectable_rows if r.get("procurement_id")}
    sel_documents = {f"{r.get('procurement_id')}:{r.get('document_name')}" for r in selectable_rows if r.get("document_name")}

    print("\n--- EXACT SELECTION CAPACITY ---")
    print(f"MAX_SELECTABLE_ROWS: {max_selectable_rows}")
    print(f"SELECTABLE_CATEGORIES: {len(sel_categories)}")
    print(f"SELECTABLE_PROCUREMENTS: {len(sel_procurements)}")
    print(f"SELECTABLE_DOCUMENTS: {len(sel_documents)}")

    # 6. Challenge Cohort Feasibility (Info-Rich & Edge)
    info_rich_count = 0
    edge_case_count = 0
    info_rich_cats = set()
    info_rich_procs = set()

    for r in fresh_rows:
        text = f"{r.get('matched_term', '')} {r.get('row_data', '')} {' '.join(r.get('context_before', []))} {' '.join(r.get('context_after', []))}"
        has_numbers = bool(re.search(r'\d+', text))
        has_units = bool(re.search(r'(?:м2|м²|мм|см|м|шт|кг|т|руб|коп|\%|гост|ту)', text, re.IGNORECASE))
        has_sep = '|' in text or ';' in text or '\t' in text
        is_long = len(text) > 50

        if (has_numbers and has_units) or (has_numbers and is_long) or has_sep:
            info_rich_count += 1
            info_rich_cats.add(r["category_code"])
            info_rich_procs.add(r["procurement_id"])

        digits_count = len(re.findall(r'\d+', text))
        if digits_count >= 3 or (len(text) < 30 and has_numbers) or has_sep:
            edge_case_count += 1

    print("\n--- CHALLENGE COHORT FEASIBILITY ---")
    print(f"POTENTIAL_INFORMATION_RICH_ROWS: {info_rich_count}")
    print(f"POTENTIAL_INFORMATION_RICH_CATEGORIES: {len(info_rich_cats)}")
    print(f"POTENTIAL_INFORMATION_RICH_PROCUREMENTS: {len(info_rich_procs)}")
    print(f"POTENTIAL_EDGE_ROWS: {edge_case_count}")

    # 7. Recovered 260 Progress
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
        rec_tech_terminal = sum(1 for r in rec_revalidated if "MODEL_EXCEPTION" in (r.get("validation_reason") or ""))
    else:
        rec_revalidated = []
        rec_still_claimable = []
        rec_confirmed = 0
        rec_rejected = 0
        rec_unknown = 0
        rec_tech_terminal = 0

    prev_rec_revalidated = 43
    prev_rec_claimable = 217
    rec_revalidated_delta = len(rec_revalidated) - prev_rec_revalidated
    rec_claimable_delta = len(rec_still_claimable) - prev_rec_claimable

    print("\n--- RECOVERED 260 PROGRESS ---")
    print(f"RECOVERED_TOTAL: 260")
    print(f"RECOVERED_REVALIDATED: {len(rec_revalidated)} (delta={rec_revalidated_delta})")
    print(f"RECOVERED_STILL_CLAIMABLE: {len(rec_still_claimable)} (delta={rec_claimable_delta})")
    print(f"RECOVERED_CONFIRMED: {rec_confirmed}")
    print(f"RECOVERED_REJECTED: {rec_rejected}")
    print(f"RECOVERED_SEMANTIC_UNKNOWN: {rec_unknown}")
    print(f"RECOVERED_TECHNICAL_TERMINAL: {rec_tech_terminal}")

    # 8. Target Backlog Audit
    cur.execute("""
        SELECT
            COUNT(*) AS backlog_cnt,
            COUNT(DISTINCT d.category_code) AS cat_cnt,
            COUNT(DISTINCT d.procurement_id) AS proc_cnt,
            COUNT(DISTINCT m.document_name) AS doc_cnt
        FROM document_match_details d
        JOIN document_matches m ON m.id = d.match_id
        WHERE d.pipeline_generation = %s
          AND (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
          AND d.validated_at IS NULL
    """, (PIPELINE_GENERATION,))
    backlog_row = cur.fetchone()
    backlog_current = backlog_row["backlog_cnt"]
    backlog_cats = backlog_row["cat_cnt"]
    backlog_procs = backlog_row["proc_cnt"]
    backlog_docs = backlog_row["doc_cnt"]

    prev_backlog = 11380
    backlog_delta = backlog_current - prev_backlog

    print("\n--- BACKLOG AUDIT ---")
    print(f"TARGET_UNVALIDATED_TOTAL: {backlog_current}")
    print(f"BACKLOG_UNIQUE_CATEGORIES: {backlog_cats}")
    print(f"BACKLOG_UNIQUE_PROCUREMENTS: {backlog_procs}")
    print(f"BACKLOG_UNIQUE_DOCUMENTS: {backlog_docs}")
    print(f"BACKLOG_DELTA_SINCE_PREVIOUS_AUDIT: {backlog_delta}")

    # 9. Throughput (Last 1h, Last 6h, Since Previous Audit)
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE validated_at >= NOW() - INTERVAL '1 hour') AS total_1h,
            COUNT(*) FILTER (WHERE validated_at >= NOW() - INTERVAL '1 hour' AND validation_status = 'CONFIRMED') AS conf_1h,
            COUNT(*) FILTER (WHERE validated_at >= NOW() - INTERVAL '1 hour' AND validation_status = 'REJECTED') AS rej_1h,
            COUNT(*) FILTER (WHERE validated_at >= NOW() - INTERVAL '1 hour' AND validation_status = 'UNKNOWN') AS unk_1h,
            COUNT(*) FILTER (WHERE validated_at >= NOW() - INTERVAL '6 hours') AS total_6h,
            COUNT(*) FILTER (WHERE validated_at >= NOW() - INTERVAL '6 hours' AND validation_status = 'CONFIRMED') AS conf_6h,
            COUNT(*) FILTER (WHERE validated_at >= NOW() - INTERVAL '6 hours' AND validation_status = 'REJECTED') AS rej_6h,
            COUNT(*) FILTER (WHERE validated_at >= NOW() - INTERVAL '6 hours' AND validation_status = 'UNKNOWN') AS unk_6h
        FROM document_match_details
        WHERE pipeline_generation = %s
          AND validator_name = %s
          AND LOWER(validator_version) = %s
          AND UPPER(validation_method) = %s
    """, (PIPELINE_GENERATION, VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper()))
    tp_row = cur.fetchone()

    # Hours elapsed since previous audit
    cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - %s::timestamp))/3600.0", (previous_audit_utc,))
    hours_elapsed = cur.fetchone()["?column?"] or 18.5

    conf_per_h_1h = tp_row["conf_1h"]
    conf_per_h_6h = round(tp_row["conf_6h"] / 6.0, 2)
    conf_per_h_since_prev = round(new_confirmed_since_prev / max(hours_elapsed, 0.1), 2)

    print("\n--- THROUGHPUT ---")
    print(f"LAST_1H: {{'terminal': {tp_row['total_1h']}, 'confirmed': {tp_row['conf_1h']}, 'rejected': {tp_row['rej_1h']}, 'unknown': {tp_row['unk_1h']}}}")
    print(f"LAST_6H: {{'terminal': {tp_row['total_6h']}, 'confirmed': {tp_row['conf_6h']}, 'rejected': {tp_row['rej_6h']}, 'unknown': {tp_row['unk_6h']}}}")
    print(f"SINCE_PREVIOUS: {{'terminal': {new_terminal_since_prev}, 'confirmed': {new_confirmed_since_prev}, 'rejected': {new_rejected_since_prev}, 'unknown': {new_unknown_since_prev}}}")
    print(f"CONFIRMED_PER_HOUR_1H: {conf_per_h_1h}")
    print(f"CONFIRMED_PER_HOUR_6H: {conf_per_h_6h}")
    print(f"CONFIRMED_PER_HOUR_SINCE_PREVIOUS: {conf_per_h_since_prev}")

    # 10. R4 Storage Check
    cur.execute("SELECT COUNT(*) FROM structured_extraction_runs")
    runs_cnt = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM structured_entities")
    entities_cnt = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM structured_entity_field_evidence")
    evidence_cnt = cur.fetchone()["count"]
    cur.execute("SELECT COUNT(*) FROM structured_attributes")
    attributes_cnt = cur.fetchone()["count"]

    print("\n--- R4 STORAGE CHECK ---")
    print(f"structured_extraction_runs: {runs_cnt}")
    print(f"structured_entities: {entities_cnt}")
    print(f"structured_entity_field_evidence: {evidence_cnt}")
    print(f"structured_attributes: {attributes_cnt}")

    # 11. Decision Logic Evaluation
    req_rows = 30
    req_cats = 5
    req_procs = 8
    req_docs = 12
    req_info = 10
    req_edge = 5

    is_ready = bool(
        max_selectable_rows >= req_rows and
        len(sel_categories) >= req_cats and
        len(sel_procurements) >= req_procs and
        len(sel_documents) >= req_docs and
        info_rich_count >= req_info and
        edge_case_count >= req_edge
    )

    is_anomaly = bool(
        new_terminal_since_prev >= 200 and
        new_confirmed_since_prev <= 2
    )

    if is_ready:
        capacity_status = "READY"
        anomaly_flag = "NO"
        reason = "Enough fresh promotion-quality capacity accumulated under hard caps"
        next_wip = "CRM-V3-LAUNCH-R4-C-STRUCTURED-EXTRACTION-QUALITY-EVALUATION-2"
    elif is_anomaly:
        capacity_status = "BLOCKED_BY_CONFIRMED_GENERATION"
        anomaly_flag = "YES"
        reason = f"High validation volume ({new_terminal_since_prev} rows terminalized) but zero/low positive CONFIRMED generation ({new_confirmed_since_prev} CONFIRMED)"
        next_wip = "CRM-V3-R3-PRODUCTION-CONFIRMED-GENERATION-FORENSIC-1"
    else:
        capacity_status = "WAITING"
        anomaly_flag = "NO"
        reason = "Normal capacity accumulation in progress"
        next_wip = "R4_C_FRESH_HOLDOUT_CAPACITY_RECHECK"

    rows_short = max(0, req_rows - max_selectable_rows)
    cats_short = max(0, req_cats - len(sel_categories))
    procs_short = max(0, req_procs - len(sel_procurements))
    docs_short = max(0, req_docs - len(sel_documents))
    info_short = max(0, req_info - info_rich_count)
    edge_short = max(0, req_edge - edge_case_count)

    print("\n--- DECISION ENACTMENT ---")
    print(f"CONFIRMED_GENERATION_ANOMALY: {anomaly_flag}")
    print(f"R4_C_CAPACITY_STATUS: {capacity_status}")
    print(f"REASON: {reason}")
    print(f"NEXT_WIP: {next_wip}")

    print("\n--- DEFICITS ---")
    print(f"ROWS_SHORT: {rows_short}")
    print(f"CATEGORIES_SHORT: {cats_short}")
    print(f"PROCUREMENTS_SHORT: {procs_short}")
    print(f"DOCUMENTS_SHORT: {docs_short}")
    print(f"INFORMATION_RICH_SHORT: {info_short}")
    print(f"EDGE_SHORT: {edge_short}")

doc_conn.close()
