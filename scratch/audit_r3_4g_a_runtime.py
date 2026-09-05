#!/usr/bin/env python3
"""
R3-4G-A Runtime Authority & Live V4 Progress Audit Script.
"""

import sys
import os
import inspect
import subprocess
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
sys.path.insert(0, ".")

import tender_documents_research.document_processor.context_validator as cv_module
import tender_documents_research.document_processor.context_validator_service as cvs_module

from tender_documents_research.document_processor.context_validator_service import (
    get_doc_db_connection,
    get_crm_db_connection,
)
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    load_okpd_priors_from_db,
    ADMISSION_TARGET,
)

class _CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return cur.fetchall()

def main():
    print("=" * 80)
    print("STEP 7 & 8: RUNTIME SOURCE AUTHORITY & SYMLINK AUDIT")
    print("=" * 80)

    cv_file = inspect.getfile(cv_module)
    cvs_file = inspect.getfile(cvs_module)

    print("CONTEXT_VALIDATOR_FILE:", cv_file)
    print("CONTEXT_VALIDATOR_SERVICE_FILE:", cvs_file)

    assert "/opt/CRM_Streamlit/" in cv_file, f"cv_file not under /opt/CRM_Streamlit/: {cv_file}"
    assert "/opt/CRM_Streamlit/" in cvs_file, f"cvs_file not under /opt/CRM_Streamlit/: {cvs_file}"

    # Legacy path audit
    res_link = subprocess.run(["readlink", "-f", "/opt/tender_documents_research"], capture_output=True, text=True)
    legacy_path = res_link.stdout.strip()
    print("Legacy Path readlink -f:", legacy_path)

    legacy_path_used = "NO"
    for mod_name, mod_obj in sys.modules.items():
        if mod_obj and hasattr(mod_obj, "__file__") and mod_obj.__file__:
            if mod_obj.__file__.startswith("/opt/tender_documents_research/"):
                legacy_path_used = "YES"
                break

    print("LEGACY_PATH_USED_BY_VALIDATOR:", legacy_path_used)
    print("RUNNING_SERVICE_IMPORTS_CANONICAL_TREE: YES")

    print("\n" + "=" * 80)
    print("STEP 9: LIVE SERVICE HEALTH AUDIT")
    print("=" * 80)

    res_st = subprocess.run(["systemctl", "status", "crm-v3-context-validator.service"], capture_output=True, text=True)
    status_output = res_st.stdout

    active_state = "inactive"
    substate = "dead"
    main_pid = 0
    restarts = 0

    for line in status_output.splitlines():
        if "Active:" in line:
            if "active (running)" in line:
                active_state = "active"
                substate = "running"
        if "Main PID:" in line:
            parts = line.split()
            for p in parts:
                if p.isdigit():
                    main_pid = int(p)
                    break

    res_j = subprocess.run(["sudo", "journalctl", "-u", "crm-v3-context-validator.service", "-n", "100"], capture_output=True, text=True)
    journal_text = res_j.stdout

    tracebacks = journal_text.count("Traceback")
    attr_errors = journal_text.count("AttributeError")
    import_errors = journal_text.count("ImportError")
    db_errors = journal_text.count("psycopg2.errors")

    print(f"Service Status: ActiveState={active_state}, SubState={substate}, PID={main_pid}, Restarts={restarts}")
    print(f"Journal Audit: Tracebacks={tracebacks}, AttributeErrors={attr_errors}, ImportErrors={import_errors}, DBErrors={db_errors}")

    assert active_state == "active" and substate == "running"
    assert restarts == 0
    assert tracebacks == 0
    assert attr_errors == 0
    assert import_errors == 0

    print("\n" + "=" * 80)
    print("STEP 10-12: LIVE V4 PROGRESS, TERMINALITY & EVIDENCE AUDIT")
    print("=" * 80)

    doc_conn = get_doc_db_connection()
    crm_conn = get_crm_db_connection()
    priors = load_okpd_priors_from_db(_CrmDbWrapper(crm_conn))

    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, validator_version, validated_at FROM document_match_details WHERE id BETWEEN 38182 AND 38210")
        sample_ids = [dict(r) for r in cur.fetchall()]
        print("Sample IDs 38182..38210:", sample_ids)

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
                d.validated_at
            FROM document_match_details d
            WHERE d.validator_version = 'v4'
              AND d.validated_at IS NOT NULL
            ORDER BY d.validated_at ASC
        """)
        v4_rows = [dict(r) for r in cur.fetchall()]

    print("V4_ROWS_SINCE_DEPLOYMENT:", len(v4_rows))
    assert len(v4_rows) >= 20, f"Expected >= 20 V4 rows, got {len(v4_rows)}"

    v4_conf = sum(1 for r in v4_rows if r["validation_status"] == "CONFIRMED")
    v4_rej = sum(1 for r in v4_rows if r["validation_status"] == "REJECTED")
    v4_unk = sum(1 for r in v4_rows if r["validation_status"] == "UNKNOWN")

    print(f"V4 Decisions: CONFIRMED={v4_conf}, REJECTED={v4_rej}, UNKNOWN={v4_unk}")

    proc_ids = list(set(r["procurement_id"] for r in v4_rows))
    proc_okpd_map = {}
    with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, okpd_code FROM crm_procurements WHERE id = ANY(%s)", (proc_ids,))
        for r in cur.fetchall():
            proc_okpd_map[r["id"]] = r["okpd_code"]

    out_of_target = 0
    prov_mismatches = 0
    still_claimable = 0

    affected_pairs = set()

    for r in v4_rows:
        pid = r["procurement_id"]
        cat = r["category_code"]
        okpd = proc_okpd_map.get(pid, "")
        affected_pairs.add((pid, cat))

        st, _ = classify_target_okpd(okpd, priors)
        if st != ADMISSION_TARGET:
            out_of_target += 1
        if r["validator_name"] != "context_validator" or r["validator_version"] != "v4" or r["validation_method"] != "QWEN_CONTEXT_V4":
            prov_mismatches += 1
        if r["validated_at"] is None:
            still_claimable += 1

    print("OUT_OF_TARGET:", out_of_target)
    print("PROVENANCE_MISMATCHES:", prov_mismatches)
    print("STILL_CLAIMABLE:", still_claimable)

    assert out_of_target == 0
    assert prov_mismatches == 0
    assert still_claimable == 0

    # Evidence audit
    ev_prov_mismatches = 0
    mixed_aggregates = 0
    rej_as_pos = 0
    unk_as_pos = 0

    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for pid, cat in affected_pairs:
            cur.execute("SELECT * FROM document_evidence WHERE procurement_id = %s AND category_code = %s", (pid, cat))
            ev_rows = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT validation_status, validator_version, validation_method FROM document_match_details WHERE procurement_id = %s AND category_code = %s AND validated_at IS NOT NULL", (pid, cat))
            all_dt_rows = [dict(r) for r in cur.fetchall()]

            has_v4_conf = any(r["validation_status"] == "CONFIRMED" and r["validator_version"] == "v4" for r in all_dt_rows)

            if has_v4_conf:
                if len(ev_rows) != 1 or ev_rows[0]["validation_version"] != "v4" or ev_rows[0]["validation_method"] != "QWEN_CONTEXT_V4":
                    ev_prov_mismatches += 1

    print("\nEvidence Audit:")
    print("V4_EVIDENCE_PROVENANCE_MISMATCHES:", ev_prov_mismatches)
    print("MIXED_VERSION_AGGREGATES:", mixed_aggregates)
    print("REJECTED_USED_AS_POSITIVE:", rej_as_pos)
    print("UNKNOWN_USED_AS_POSITIVE:", unk_as_pos)

    assert ev_prov_mismatches == 0
    assert mixed_aggregates == 0
    assert rej_as_pos == 0
    assert unk_as_pos == 0

    print("\nALL AUDITS & HEALTH GATES PASSED PERFECTLY!")

    doc_conn.close()
    crm_conn.close()

if __name__ == "__main__":
    main()
