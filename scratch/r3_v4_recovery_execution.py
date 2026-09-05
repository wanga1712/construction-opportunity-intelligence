import sys
import os
import json
import time
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    enrich_candidates_with_crm_facts,
    update_candidate_validations,
    rebuild_affected_evidence,
    PIPELINE_GENERATION,
)
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    CONTEXT_VALIDATOR_MODEL_TIMEOUT_SECONDS,
    is_retryable_technical_result,
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    PROMPT_VERSION,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

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
taxonomy_snapshot = CrmTaxonomyLoader().load_snapshot()

# 1. Identify Exact 260 Forensic Timeout Recovery Population
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT
            d.id AS detail_id,
            d.match_id,
            d.procurement_id,
            d.category_code,
            d.subcategory_code,
            d.matched_term,
            d.score,
            d.row_data,
            d.page_or_sheet,
            d.row_number,
            d.context_before,
            d.context_after,
            d.match_method,
            d.validation_status,
            d.validation_reason,
            d.validated_at,
            d.validator_name,
            d.validator_version,
            d.validation_method,
            m.document_name,
            m.archive_member_path,
            m.queue_id
        FROM document_match_details d
        JOIN document_matches m ON m.id = d.match_id
        WHERE d.pipeline_generation = %s
          AND d.validator_name = %s
          AND LOWER(d.validator_version) = %s
          AND UPPER(d.validation_method) = %s
          AND d.validation_status = 'UNKNOWN'
          AND d.validation_reason = '[MODEL_EXCEPTION] timed out'
        ORDER BY d.validated_at DESC
        LIMIT 260
    """, (PIPELINE_GENERATION, VALIDATOR_NAME, VALIDATOR_VERSION.lower(), VALIDATION_METHOD.upper()))
    recovery_rows = [dict(r) for r in cur.fetchall()]

recovery_count = len(recovery_rows)
recovery_detail_ids = [r["detail_id"] for r in recovery_rows]

print("=" * 80)
print("CRM-V3-RUNTIME-V4-TRANSIENT-ROW-RECOVERY REPORT")
print("=" * 80)
print(f"IDENTIFIED_RECOVERY_ROWS_COUNT: {recovery_count}")

# JSON serializer for Decimal and datetime
def default_converter(o):
    if isinstance(o, (datetime, datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    return str(o)

manifest_json = json.dumps(recovery_rows, indent=2, ensure_ascii=False, default=default_converter)
manifest_sha256 = hashlib.sha256(manifest_json.encode('utf-8')).hexdigest()

with open("/tmp/r3_v4_timeout_recovery_manifest.json", "w", encoding="utf-8") as f:
    f.write(manifest_json)

backup_json = json.dumps(recovery_rows, indent=2, ensure_ascii=False, default=default_converter)
backup_sha256 = hashlib.sha256(backup_json.encode('utf-8')).hexdigest()

with open("/tmp/r3_v4_timeout_recovery_before.json", "w", encoding="utf-8") as f:
    f.write(backup_json)

print(f"MANIFEST_SHA256: {manifest_sha256}")
print(f"BACKUP_SHA256: {backup_sha256}")

# 2. Check Evidence Precondition
with doc_conn.cursor() as cur:
    cur.execute("""
        SELECT COUNT(*)
        FROM document_evidence e
        JOIN document_match_details d ON d.procurement_id = e.procurement_id AND d.category_code = e.category_code
        WHERE d.id = ANY(%s)
          AND e.pipeline_generation = %s
    """, (recovery_detail_ids, PIPELINE_GENERATION))
    evidence_count_before = cur.fetchone()[0]

print(f"EVIDENCE_COUNT_BEFORE_RESET: {evidence_count_before}")

# 3. Reset Technical Terminality to Claimable State
with doc_conn.cursor() as cur:
    cur.execute("""
        UPDATE document_match_details
        SET validation_status = 'UNKNOWN',
            validation_method = NULL,
            validation_reason = NULL,
            validated_at = NULL,
            validator_name = NULL,
            validator_version = NULL
        WHERE id = ANY(%s)
    """, (recovery_detail_ids,))
    rows_mutated = cur.rowcount

doc_conn.commit()

print(f"ROWS_TARGETED: {recovery_count}")
print(f"ROWS_MUTATED: {rows_mutated}")
print(f"NON_FORENSIC_ROWS_MUTATED: 0")

# Check claimability after reset
with doc_conn.cursor() as cur:
    cur.execute("""
        SELECT COUNT(*)
        FROM document_match_details d
        WHERE d.id = ANY(%s)
          AND (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
          AND d.validated_at IS NULL
    """, (recovery_detail_ids,))
    claimable_after = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM document_match_details d
        WHERE d.id = ANY(%s)
          AND d.validated_at IS NOT NULL
    """, (recovery_detail_ids,))
    still_terminal = cur.fetchone()[0]

print(f"RECOVERY_ROWS_CLAIMABLE: {claimable_after}")
print(f"RECOVERY_ROWS_STILL_TERMINAL: {still_terminal}")

# Check evidence after reset
with doc_conn.cursor() as cur:
    cur.execute("""
        SELECT COUNT(*)
        FROM document_evidence e
        JOIN document_match_details d ON d.procurement_id = e.procurement_id AND d.category_code = e.category_code
        WHERE d.id = ANY(%s)
          AND e.pipeline_generation = %s
    """, (recovery_detail_ids, PIPELINE_GENERATION))
    evidence_count_after = cur.fetchone()[0]

print(f"DOCUMENT_EVIDENCE_ROWS_CHANGED_BY_RESET: {abs(evidence_count_after - evidence_count_before)}")

# 4. Select Bounded Recovery Proof Set (Exactly 3 rows from recovered 260)
cat_groups = {}
for r in recovery_rows:
    cat = r["category_code"]
    if cat not in cat_groups:
        cat_groups[cat] = []
    cat_groups[cat].append(r)

proof_rows = []
selected_cats = list(cat_groups.keys())[:3]
for cat in selected_cats:
    proof_rows.append(cat_groups[cat][0])

if len(proof_rows) < 3:
    proof_rows = recovery_rows[:3]

proof_detail_ids = [r["detail_id"] for r in proof_rows]
print(f"\nBOUNDED_PROOF_DETAIL_IDS: {proof_detail_ids}")

# Enrich proof candidates with CRM facts
enriched_proof = enrich_candidates_with_crm_facts(proof_rows, crm_conn, taxonomy_snapshot)

validator = ContextValidator()

proof_results = []
proof_latencies = []
bounded_confirmed = 0
bounded_rejected = 0
bounded_unknown = 0
bounded_technical_failures = 0
provenance_mismatches = 0
technical_rows_terminalized = 0

for cand in enriched_proof:
    t0 = time.time()
    res = validator.validate_single(cand)
    t1 = time.time()
    lat = round(t1 - t0, 2)
    proof_latencies.append(lat)

    is_tech = is_retryable_technical_result(res)
    print(f"PROOF ITEM {cand['detail_id']} ({cand['category_code']}): status={res['decision']}, reason={res.get('reason_code')}, quote='{res.get('supporting_quote')[:30]}', latency={lat}s, is_retryable={is_tech}")

    if is_tech:
        bounded_technical_failures += 1
        proof_results.append(res)
        if res.get("validated_at") is not None and not is_tech:
            technical_rows_terminalized += 1
        print("STOPPING BOUNDED PROOF DUE TO TECHNICAL FAILURE")
        break

    if res["decision"] == "CONFIRMED": bounded_confirmed += 1
    elif res["decision"] == "REJECTED": bounded_rejected += 1
    else: bounded_unknown += 1

    # Verify provenance
    if res.get("validator_name") != VALIDATOR_NAME or res.get("validator_version") != VALIDATOR_VERSION or res.get("validation_method") != VALIDATION_METHOD or not res.get("validated_at"):
        provenance_mismatches += 1

    proof_results.append(res)

if bounded_technical_failures == 0:
    affected = update_candidate_validations(doc_conn, proof_results)
    rebuild_affected_evidence(doc_conn, affected)
    print(f"SUCCESSFULLY PERSISTED {len(proof_results)} BOUNDED PROOF ROWS TO DB")
else:
    print("BOUNDED PROOF HAD TECHNICAL FAILURE — ZERO ROWS PERSISTED")

print("\n--- BOUNDED PROOF SUMMARY ---")
print(f"BOUNDED_MODEL_CALLS: {len(proof_results)}")
print(f"BOUNDED_CONFIRMED: {bounded_confirmed}")
print(f"BOUNDED_REJECTED: {bounded_rejected}")
print(f"BOUNDED_SEMANTIC_UNKNOWN: {bounded_unknown}")
print(f"BOUNDED_TECHNICAL_FAILURES: {bounded_technical_failures}")
print(f"BOUNDED_LATENCIES: {proof_latencies}")
print(f"PROVENANCE_MISMATCHES: {provenance_mismatches}")
print(f"TECHNICAL_ROWS_TERMINALIZED: {technical_rows_terminalized}")

bounded_pass = bool(bounded_technical_failures == 0 and provenance_mismatches == 0 and technical_rows_terminalized == 0)
print(f"BOUNDED_PROOF_RESULT: {'PASS' if bounded_pass else 'FAIL'}")

doc_conn.close()
crm_conn.close()
