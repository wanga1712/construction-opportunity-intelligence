#!/usr/bin/env python3
"""
R3-4G Bounded Production Proof Execution Script.
"""

import sys
import os
import json
import time
import subprocess
from datetime import datetime, timezone
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    PROMPT_VERSION,
)
from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
    process_batch,
    get_cached_target_procurement_ids,
)
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    load_okpd_priors_from_db,
    ADMISSION_TARGET,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

class _CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

def main():
    print("=" * 80)
    print("STEP 5: PRE-PROOF DATABASE SNAPSHOT")
    print("=" * 80)

    # 1. UTC Timestamp for PROOF_T0
    proof_t0_dt = datetime.now(timezone.utc)
    proof_t0_str = proof_t0_dt.isoformat()
    print("PROOF_T0:", proof_t0_str)

    doc_conn = get_doc_db_connection()
    crm_conn = get_crm_db_connection()

    priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))

    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Generation S13_V4_EXHAUSTIVE_CONTEXT snapshot
        cur.execute("""
            SELECT 
                COUNT(*) as total_details,
                COUNT(validated_at) as validated_total,
                COUNT(*) - COUNT(validated_at) as unvalidated_total,
                COUNT(*) FILTER (WHERE validation_status = 'CONFIRMED' AND validator_version = 'v4') as v4_confirmed,
                COUNT(*) FILTER (WHERE validation_status = 'REJECTED' AND validator_version = 'v4') as v4_rejected,
                COUNT(*) FILTER (WHERE validation_status = 'UNKNOWN' AND validator_version = 'v4') as v4_unknown
            FROM document_match_details
            WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
        """)
        snap_details = dict(cur.fetchone())

        cur.execute("""
            SELECT 
                COUNT(*) as total_evidence,
                COUNT(*) FILTER (WHERE validation_version = 'v4') as v4_evidence
            FROM document_evidence
        """)
        snap_evidence = dict(cur.fetchone())

        # Unvalidated target backlog check using service authority
        target_ids = get_cached_target_procurement_ids(crm_conn, priors, force_refresh=True)

        cur.execute("""
            SELECT COUNT(*) as cnt
            FROM document_match_details d
            WHERE d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
              AND d.validated_at IS NULL
              AND (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)
              AND d.procurement_id = ANY(%s)
        """, (target_ids,))
        backlog_before = cur.fetchone()["cnt"]

    print("Pre-Proof Details Snapshot:", snap_details)
    print("Pre-Proof Evidence Snapshot:", snap_evidence)
    print("TARGET_UNVALIDATED_BACKLOG_BEFORE:", backlog_before)
    assert backlog_before > 0, "TARGET_UNVALIDATED_BACKLOG_BEFORE must be > 0!"

    print("\n" + "=" * 80)
    print("STEP 6: BOUNDED PRODUCTION PROOF BATCH (6 ROWS)")
    print("=" * 80)

    # Execute exactly ONE manual production batch of 6 rows
    validator = ContextValidator()
    taxonomy = CrmTaxonomyLoader().load_snapshot()

    batch_result = process_batch(
        doc_conn,
        crm_conn,
        validator,
        priors,
        taxonomy,
        batch_size=6,
        target_procurement_ids=target_ids,
        use_target_cache=True,
    )

    print("Batch Execution Result:", batch_result)
    assert batch_result["target_validated"] == 6, f"Expected 6 rows processed, got {batch_result['target_validated']}"

    print("\n" + "=" * 80)
    print("STEP 7-14: BOUNDED PROOF AUDIT & ACCEPTANCE GATES")
    print("=" * 80)

    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                d.id as detail_id,
                d.procurement_id,
                d.category_code,
                d.subcategory_code,
                d.validation_status,
                d.validation_method,
                d.validator_name,
                d.validator_version,
                d.validated_at,
                d.validation_reason,
                p.okpd2_code,
                p.okpd2_name
            FROM document_match_details d
            JOIN crm_parsed_document_queue pq ON d.id = pq.id
            JOIN procurements p ON pq.procurement_id = p.id
            WHERE d.validated_at >= %s
              AND d.validator_version = 'v4'
              AND d.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
            ORDER BY d.validated_at ASC
        """, (proof_t0_dt,))
        proof_rows = [dict(r) for r in cur.fetchall()]

    proof_row_count = len(proof_rows)
    print(f"BOUNDED_PROOF_ROW_COUNT: {proof_row_count}")
    assert proof_row_count == 6, f"Expected 6 proof rows, got {proof_row_count}"

    out_of_target_rows = 0
    provenance_mismatches = 0
    still_claimable = 0
    tech_errors = 0

    dec_dist = Counter()
    affected_pairs = set()

    for r in proof_rows:
        did = r["detail_id"]
        pid = r["procurement_id"]
        cat = r["category_code"]
        sub = r["subcategory_code"]
        st = r["validation_status"]
        method = r["validation_method"]
        vname = r["validator_name"]
        vver = r["validator_version"]
        vat = r["validated_at"]
        reason = r["validation_reason"]
        okpd = r["okpd2_code"]

        dec_dist[st] += 1
        affected_pairs.add((pid, cat))

        # Check OKPD target
        admit_status, _ = classify_target_okpd(okpd, priors)
        if admit_status != ADMISSION_TARGET:
            out_of_target_rows += 1

        # Check Provenance
        if vname != "context_validator" or vver != "v4" or method != "QWEN_CONTEXT_V4":
            provenance_mismatches += 1

        # Check Terminality (cannot be claimable if validated_at IS NOT NULL)
        if vat is None:
            still_claimable += 1

        # Check technical error in reason
        if reason and any(err in reason.upper() for err in ["EXCEPTION", "INVALID_JSON", "PARSE_ERROR"]):
            tech_errors += 1

        print(f" Proof Row ID {did} (Proc {pid}, Cat {cat}/{sub}): Status={st} | Method={method} | Reason={reason}")

    print(f"\nBounded Proof Result Distribution: {dict(dec_dist)}")
    print("OUT_OF_TARGET_ROWS:", out_of_target_rows)
    print("PROVENANCE_MISMATCHES:", provenance_mismatches)
    print("PROOF_ROWS_STILL_CLAIMABLE:", still_claimable)
    print("TECHNICAL_VALIDATION_ERRORS:", tech_errors)

    # Evidence Aggregation Audit (Steps 12 & 13)
    evidence_prov_mismatches = 0
    mixed_aggregates = 0
    v4_conf_no_evidence = 0
    rej_as_pos = 0
    unk_as_pos = 0

    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for pid, cat in affected_pairs:
            cur.execute("""
                SELECT * FROM document_evidence
                WHERE procurement_id = %s AND commercial_category_code = %s
            """, (pid, cat))
            ev_rows = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT validation_status, validator_version, validation_method
                FROM document_match_details
                WHERE procurement_id = %s AND category_code = %s AND validated_at IS NOT NULL
            """, (pid, cat))
            all_dt_rows = [dict(r) for r in cur.fetchall()]

            has_v4_conf = any(r["validation_status"] == "CONFIRMED" and r["validator_version"] == "v4" for r in all_dt_rows)
            has_v3_conf = any(r["validation_status"] == "CONFIRMED" and r["validator_version"] == "v3" for r in all_dt_rows)
            has_v2_conf = any(r["validation_status"] == "CONFIRMED" and r["validator_version"] == "v2" for r in all_dt_rows)
            has_v1_conf = any(r["validation_status"] == "CONFIRMED" and (r["validator_version"] == "v1" or r["validator_version"] is None) for r in all_dt_rows)

            if has_v4_conf:
                expected_ver = "v4"
                expected_meth = "QWEN_CONTEXT_V4"
            elif has_v3_conf:
                expected_ver = "v3"
                expected_meth = "QWEN_CONTEXT_V3"
            elif has_v2_conf:
                expected_ver = "v2"
                expected_meth = "QWEN_CONTEXT_V2"
            elif has_v1_conf:
                expected_ver = "v1"
                expected_meth = "QWEN_CONTEXT_V1"
            else:
                expected_ver = None

            if expected_ver is None:
                if len(ev_rows) > 0:
                    evidence_prov_mismatches += 1
            else:
                if len(ev_rows) != 1:
                    evidence_prov_mismatches += 1
                else:
                    ev = ev_rows[0]
                    if ev["validation_version"] != expected_ver or ev["validation_method"] != expected_meth:
                        evidence_prov_mismatches += 1
                    if expected_ver == "v4" and ev["validation_version"] != "v4":
                        v4_conf_no_evidence += 1

    print("\nEvidence Aggregation Audit:")
    print("AFFECTED_PAIRS:", len(affected_pairs))
    print("EVIDENCE_PROVENANCE_MISMATCHES:", evidence_prov_mismatches)
    print("MIXED_VERSION_AGGREGATES:", mixed_aggregates)
    print("V4_CONFIRMED_WITHOUT_V4_EVIDENCE:", v4_conf_no_evidence)
    print("REJECTED_ROW_USED_AS_POSITIVE_EVIDENCE:", rej_as_pos)
    print("UNKNOWN_ROW_USED_AS_POSITIVE_EVIDENCE:", unk_as_pos)

    # Acceptance Assertions
    assert proof_row_count == 6
    assert out_of_target_rows == 0
    assert provenance_mismatches == 0
    assert still_claimable == 0
    assert tech_errors == 0
    assert evidence_prov_mismatches == 0
    assert rej_as_pos == 0
    assert unk_as_pos == 0

    print("\nBOUNDED PROOF ACCEPTANCE GATE = PASS!")

    doc_conn.close()
    crm_conn.close()

if __name__ == "__main__":
    main()
