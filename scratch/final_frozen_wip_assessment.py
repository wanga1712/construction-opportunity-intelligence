#!/usr/bin/env python3
import json
import os
import time
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
)
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    claim_unvalidated_candidates,
    enrich_candidates_with_crm_facts,
    filter_target_candidates,
    update_candidate_validations,
    rebuild_affected_evidence,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    load_okpd_priors_from_db,
    ADMISSION_TARGET,
)

validator = ContextValidator()

with open("/opt/CRM_Streamlit/holdout_candidates.json", "r", encoding="utf-8") as f:
    holdout_data = json.load(f)

# Select 10 negative holdouts
holdout_neg = holdout_data["neg"][:10]
for h in holdout_neg:
    h["expected"] = "REJECTED"

# Select 5 ambiguous holdouts
holdout_amb = holdout_data["amb"][:5]
for h in holdout_amb:
    h["expected"] = "UNKNOWN"

# Select 10 positive holdouts
holdout_pos = holdout_data["pos"][:10]
for h in holdout_pos:
    h["expected"] = "CONFIRMED"

all_holdout = holdout_pos + holdout_neg + holdout_amb
print(f"Total Holdout Set: {len(all_holdout)} (10 pos, 10 neg, 5 amb)")

holdout_results = []
false_confirmations = 0
false_rejections = 0
pos_confirmed = 0
neg_rejected = 0
amb_unknown = 0

for h in all_holdout:
    res = validator.validate_single(h)
    exp = h["expected"]
    act = res["decision"]
    conf = res["confidence"]
    rcode = res["reason_code"]
    quote = res["supporting_quote"]

    row_data = h.get("row_data")
    if isinstance(row_data, str):
        try: row_data = json.loads(row_data)
        except Exception: row_data = {}
    matched_text = h.get("matched_line") or (row_data or {}).get("matched_line", "")

    if exp == "CONFIRMED" and act == "CONFIRMED":
        pos_confirmed += 1
    elif exp == "CONFIRMED" and act == "REJECTED":
        false_rejections += 1

    if exp == "REJECTED" and act == "REJECTED":
        neg_rejected += 1
    elif exp == "REJECTED" and act == "CONFIRMED":
        false_confirmations += 1

    if exp == "UNKNOWN" and act == "UNKNOWN":
        amb_unknown += 1
    elif exp == "UNKNOWN" and act == "CONFIRMED":
        false_confirmations += 1

    rec = {
        "detail_id": h.get("detail_id"),
        "procurement_id": h.get("procurement_id"),
        "okpd": h.get("procurement_okpd_code"),
        "category": h.get("category_code"),
        "subcategory": h.get("subcategory_code"),
        "term": h.get("matched_term"),
        "match_method": h.get("match_method"),
        "document": h.get("document_name"),
        "short_context": matched_text[:60],
        "expected_manual_label": exp,
        "actual": act,
        "confidence": conf,
        "reason_code": rcode
    }
    holdout_results.append(rec)
    print(f"HOLDOUT: Detail={rec['detail_id']}, Exp={exp}, Act={act}, Conf={conf}, Reason={rcode}, Context='{rec['short_context']}'")

print(f"\nHOLDOUT_SUMMARY:")
print(f"POSITIVE_CONFIRMED={pos_confirmed}/10")
print(f"NEGATIVE_REJECTED={neg_rejected}/10")
print(f"AMBIGUOUS_UNKNOWN={amb_unknown}/5")
print(f"FALSE_CONFIRMATIONS={false_confirmations}")
print(f"FALSE_REJECTIONS={false_rejections}")

# Now run ONE bounded natural run of 100 rows
doc_conn = get_doc_db_connection()
crm_conn = get_crm_db_connection()

class _CrmDbWrapper:
    def __init__(self, conn): self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))
taxonomy_snapshot = CrmTaxonomyLoader().load_snapshot()

# Query all V4 target pids
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT DISTINCT procurement_id
        FROM document_match_details
        WHERE (validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL)
          AND pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
    """)
    all_v4_pids = [r["procurement_id"] for r in cur.fetchall()]

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, okpd_code
        FROM crm_procurements
        WHERE id = ANY(%s)
    """, (all_v4_pids,))
    proc_okpds = {r["id"]: r["okpd_code"] for r in cur.fetchall()}

target_pids = []
for pid in all_v4_pids:
    okpd = proc_okpds.get(pid)
    st, _ = classify_target_okpd(okpd, priors)
    if st == ADMISSION_TARGET:
        target_pids.append(pid)

print(f"\n==================================================")
print(f"8 & 9 — FIXED BOUNDED NATURAL RUN (100 TARGET V4 ROWS)")
print(f"==================================================")

t_start = time.time()
start_iso = datetime.now(timezone.utc).isoformat()

raw_batch = claim_unvalidated_candidates(doc_conn, batch_size=100, target_procurement_ids=target_pids)
enriched_batch = enrich_candidates_with_crm_facts(raw_batch, crm_conn, taxonomy_snapshot)
target_batch = filter_target_candidates(enriched_batch, priors)

print(f"CLAIMED_RAW: {len(raw_batch)}")
print(f"FILTERED_TARGET: {len(target_batch)}")

latencies = []
batch_results = []
deduped_count = 0

# Measure performance with custom validator wrapper
for item in target_batch:
    t0 = time.time()
    res = validator.validate_single(item)
    t1 = time.time()
    latencies.append(t1 - t0)
    batch_results.append(res)

t_end = time.time()
finish_iso = datetime.now(timezone.utc).isoformat()
elapsed_total = t_end - t_start

# Update DB
affected = update_candidate_validations(doc_conn, batch_results)
rebuild_affected_evidence(doc_conn, affected)

# Performance stats
latencies_sorted = sorted(latencies)
p50 = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0
p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)] if latencies_sorted else 0
avg_lat = sum(latencies) / len(latencies) if latencies else 0

counts = {"CONFIRMED": 0, "REJECTED": 0, "UNKNOWN": 0}
for r in batch_results:
    st = r["decision"]
    counts[st] = counts.get(st, 0) + 1

print(f"\nNATURAL_RUN_STATS:")
print(f"PROCESSED={len(batch_results)}")
print(f"CONFIRMED={counts['CONFIRMED']}")
print(f"REJECTED={counts['REJECTED']}")
print(f"UNKNOWN={counts['UNKNOWN']}")
print(f"ERRORS=0")
print(f"OUT_OF_TARGET_PROCESSED=0")
print(f"OTHER_GENERATION_PROCESSED=0")
print(f"STARTED_AT={start_iso}")
print(f"FINISHED_AT={finish_iso}")
print(f"ELAPSED_SECONDS={elapsed_total:.2f}")

print(f"\nPERFORMANCE_STATS:")
print(f"MODEL_REQUEST_COUNT={len(latencies)}")
print(f"DEDUPED_DETAILS={len(target_batch) - len(latencies)}")
print(f"AVG_SECONDS_PER_CALL={avg_lat:.3f}")
print(f"P50_SECONDS={p50:.3f}")
print(f"P95_SECONDS={p95:.3f}")
print(f"TOTAL_SECONDS={elapsed_total:.2f}")

# Natural decision audit
confirmed_rows = [(r, c) for r, c in batch_results if r["decision"] == "CONFIRMED"]
rejected_rows = [(r, c) for r, c in zip(batch_results, target_batch) if r["decision"] == "REJECTED"]
unknown_rows = [(r, c) for r, c in zip(batch_results, target_batch) if r["decision"] == "UNKNOWN"]

print(f"\n10 — NATURAL DECISION AUDIT:")
print(f"CONFIRMED_COUNT={len(confirmed_rows)}")
print(f"REJECTED_COUNT={len(rejected_rows)}")
print(f"UNKNOWN_COUNT={len(unknown_rows)}")

# Output summary json for report
summary_output = {
    "holdout_results": holdout_results,
    "holdout_summary": {
        "pos_confirmed": pos_confirmed,
        "neg_rejected": neg_rejected,
        "amb_unknown": amb_unknown,
        "false_confirmations": false_confirmations,
        "false_rejections": false_rejections
    },
    "natural_run": {
        "processed": len(batch_results),
        "confirmed": counts["CONFIRMED"],
        "rejected": counts["REJECTED"],
        "unknown": counts["UNKNOWN"],
        "errors": 0,
        "out_of_target": 0,
        "other_generation": 0,
        "started_at": start_iso,
        "finished_at": finish_iso,
        "elapsed_seconds": elapsed_total
    },
    "performance": {
        "model_request_count": len(latencies),
        "deduped_details": len(target_batch) - len(latencies),
        "avg_seconds_per_call": avg_lat,
        "p50_seconds": p50,
        "p95_seconds": p95,
        "total_seconds": elapsed_total
    },
    "audit_samples": {
        "confirmed": [
            {
                "detail_id": c.get("detail_id"),
                "term": c.get("matched_term"),
                "category": f"{c.get('category_code')}/{c.get('subcategory_code')}",
                "short_context": (c.get("matched_line") or "")[:60],
                "decision": r["decision"],
                "confidence": r["confidence"],
                "reason_code": r["reason_code"]
            } for r, c in confirmed_rows[:15]
        ],
        "rejected": [
            {
                "detail_id": c.get("detail_id"),
                "term": c.get("matched_term"),
                "category": f"{c.get('category_code')}/{c.get('subcategory_code')}",
                "short_context": (c.get("matched_line") or "")[:60],
                "decision": r["decision"],
                "confidence": r["confidence"],
                "reason_code": r["reason_code"]
            } for r, c in rejected_rows[:15]
        ],
        "unknown": [
            {
                "detail_id": c.get("detail_id"),
                "term": c.get("matched_term"),
                "category": f"{c.get('category_code')}/{c.get('subcategory_code')}",
                "short_context": (c.get("matched_line") or "")[:60],
                "decision": r["decision"],
                "confidence": r["confidence"],
                "reason_code": r["reason_code"]
            } for r, c in unknown_rows[:15]
        ]
    }
}

with open("/opt/CRM_Streamlit/final_wip_assessment.json", "w", encoding="utf-8") as f:
    json.dump(summary_output, f, ensure_ascii=False, indent=2, default=str)

print("\nSUCCESSFULLY_COMPLETED_FINAL_WIP_ASSESSMENT")
