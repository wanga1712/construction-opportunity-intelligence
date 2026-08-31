#!/usr/bin/env python3
"""Cleanup out-of-target queue rows from document_processing_queue.

Transitions rows with status in ('PENDING', 'PRE_RESEARCH_WAITING') and having out-of-target OKPD codes
to FAILED status with last_error = 'OUT_OF_TARGET_OKPD' and category_context updated with
OUT_OF_TARGET_CAN_ENTER_TRAINING = 'NO'.
"""

import os
import sys
import json
import psycopg2
import psycopg2.extras
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db, match_okpd_priors

def clean_queue():
    from dotenv import load_dotenv
    load_dotenv("/opt/CRM_Streamlit/.env")

    crm_dsn = {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_NAME", "crm"),
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }

    doc_dsn = {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }

    print("Connecting to CRM database on S13...")
    try:
        crm_conn = psycopg2.connect(**crm_dsn)
    except Exception as exc:
        print(f"Failed to connect to CRM DB: {exc}")
        sys.exit(1)

    class CrmDbWrapper:
        def __init__(self, conn):
            self.conn = conn
        def execute_query(self, sql, params=None):
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    crm_db = CrmDbWrapper(crm_conn)

    # Load target OKPD priors
    print("Loading active target OKPD priors...")
    priors = load_okpd_priors_from_db(crm_db)
    print(f"Loaded {len(priors)} active OKPD priors.")

    print("Connecting to Document DB on S13...")
    try:
        doc_conn = psycopg2.connect(**doc_dsn)
    except Exception as exc:
        print(f"Failed to connect to Document DB: {exc}")
        crm_conn.close()
        sys.exit(1)

    doc_conn.autocommit = False
    cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Fetch all unstarted queue rows for S13_V4_EXHAUSTIVE_CONTEXT
        print("Querying unstarted tasks in the document processing queue...")
        cur.execute(
            """
            SELECT id, procurement_id, status, category_context
            FROM document_processing_queue
            WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
              AND status IN ('PRE_RESEARCH_WAITING', 'PENDING')
            """
        )
        queue_rows = cur.fetchall()
        print(f"Found {len(queue_rows)} unstarted queue tasks.")

        # Batch query OKPD codes for all procurement_ids
        pids = list({r["procurement_id"] for r in queue_rows})
        proc_okpds = {}
        if pids:
            print("Fetching OKPD codes for opportunities...")
            chunk_size = 500
            for i in range(0, len(pids), chunk_size):
                chunk = pids[i : i + chunk_size]
                placeholders = ",".join(["%s"] * len(chunk))
                sql = f"SELECT id, okpd_code FROM crm_procurements WHERE id IN ({placeholders})"
                rows = crm_db.execute_query(sql, tuple(chunk))
                for r in rows:
                    proc_okpds[r["id"]] = r["okpd_code"]

        print("Checking opportunities against target priors...")
        cleaned_count = 0
        for r in queue_rows:
            pid = r["procurement_id"]
            okpd = proc_okpds.get(pid)

            # Match OKPD
            matched = match_okpd_priors(okpd, priors)
            if not matched:
                # Transition out-of-target row to FAILED
                cat_ctx = r["category_context"] or {}
                if isinstance(cat_ctx, str):
                    cat_ctx = json.loads(cat_ctx)
                cat_ctx["OUT_OF_TARGET_CAN_ENTER_TRAINING"] = "NO"
                cat_ctx["exclusion_reason"] = "OUT_OF_TARGET_OKPD"

                cur.execute(
                    """
                    UPDATE document_processing_queue
                    SET status = 'FAILED',
                        last_error = 'OUT_OF_TARGET_OKPD',
                        category_context = %s
                    WHERE id = %s
                    """,
                    (psycopg2.extras.Json(cat_ctx), r["id"]),
                )
                cleaned_count += 1
                if cleaned_count % 1000 == 0:
                    print(f"Cleaned {cleaned_count} rows...")

        doc_conn.commit()
        print(f"Cleanup finished. Successfully transitioned {cleaned_count} out-of-target opportunities to FAILED.")
    except Exception as exc:
        doc_conn.rollback()
        print(f"Error occurred during cleanup: {exc}")
        sys.exit(1)
    finally:
        doc_conn.close()
        crm_conn.close()

if __name__ == "__main__":
    clean_queue()
