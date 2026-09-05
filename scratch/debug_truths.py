import os
import sys
import json
import psycopg2
import psycopg2.extras

os.environ["CRM_DB_USER"] = "crm_app"
os.environ["CRM_DB_PASSWORD"] = "X17B3n5hbANQSRt6i7WIyy0lJudX"
os.environ["CRM_DB_HOST"] = "127.0.0.1"
os.environ["CRM_DB_PORT"] = "5432"
os.environ["S13_DOCUMENT_DB_USER"] = "doc_worker"
os.environ["S13_DOCUMENT_DB_PASSWORD"] = "F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT"
os.environ["S13_DOCUMENT_DB_HOST"] = "127.0.0.1"
os.environ["S13_DOCUMENT_DB_PORT"] = "5432"

sys.path.append("/opt/CRM_Streamlit_rescue")
sys.path.append("/opt/pythonProject89")

from src.services.commercial_routing_v3.learning_observer import LearningObserver, get_doc_db, get_crm_db, PIPELINE_GENERATION, PRODUCER_VERSION

observer = LearningObserver()
doc_conn = get_doc_db()
crm_conn = get_crm_db()

try:
    cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, procurement_id, queue_lane, priority_score, status, research_generation_hash, completed_at
        FROM document_processing_queue
        WHERE pipeline_generation = %s AND status IN ('COMPLETED', 'FAILED', 'NO_LINKS') AND procurement_id < 100
        ORDER BY id DESC
    """, (PIPELINE_GENERATION,))
    term_items = cur.fetchall()
    print(f"Found {len(term_items)} terminal queue items with PID < 100 to check.")

    for item in term_items:
        pid = item["procurement_id"]
        gen_hash = item["research_generation_hash"] or "dummy"
        qid = item["id"]
        print(f"\nChecking QID={qid}, PID={pid}, Hash={gen_hash[:10]}...")

        with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c_cur:
            c_cur.execute("""
                SELECT document_manifest_json FROM crm_v3_pre_research_snapshots
                WHERE procurement_id = %s
            """, (pid,))
            snap_row = c_cur.fetchone()
            if not snap_row:
                print(f"  No snapshot found for PID={pid}!")
                continue
            
            manifest = snap_row["document_manifest_json"]
            if isinstance(manifest, str):
                manifest = json.loads(manifest)
            print(f"  Manifest has {len(manifest)} files.")

            with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as d_cur:
                d_cur.execute("""
                    SELECT f.id as source_document_id, f.file_name, f.download_status, f.downloaded_at, f.created_at as file_created_at,
                           r.status as parse_status, r.completed_at as parse_completed_at
                    FROM document_files f
                    LEFT JOIN document_processing_results r ON f.id = r.file_id
                    WHERE f.procurement_id = %s
                """, (pid,))
                doc_results = d_cur.fetchall()
            print(f"  document_files has {len(doc_results)} rows.")

            doc_map = {dr["source_document_id"]: dr for dr in doc_results}
            doc_name_map = {}
            for dr in doc_results:
                if dr.get("file_name"):
                    doc_name_map[dr["file_name"].strip().lower()] = dr

            c_cur.execute("""
                SELECT source_document_id FROM crm_v3_raw_source_evidence
                WHERE procurement_id = %s
            """, (pid,))
            ev_rows = c_cur.fetchall()
            print(f"  Raw evidence has {len(ev_rows)} rows.")

            ev_doc_ids = set()
            for ev in ev_rows:
                if ev.get("source_document_id"):
                    ev_doc_ids.add(ev["source_document_id"])

            useful_docs = []
            non_useful_docs = []
            unknown_docs = []

            for d in manifest:
                d_id = d.get("source_document_id")
                d_name = d.get("document_name")
                d_key = d.get("document_key")
                d_item = {"document_key": d_key, "source_document_id": d_id, "document_name": d_name}

                dr = doc_map.get(d_id)
                matched_via = "ID"
                if not dr and d_name:
                    dr = doc_name_map.get(d_name.strip().lower())
                    matched_via = "NAME"

                if not dr:
                    print(f"    File '{d_name}' (ID={d_id}) not found in document_files!")
                    unknown_docs.append(d_item)
                    continue

                dl_st = str(dr.get("download_status") or "").upper()
                pr_st = str(dr.get("parse_status") or "").upper() if dr.get("parse_status") else None
                print(f"    File '{d_name}': download_status={dl_st}, parse_status={pr_st} (matched via {matched_via})")

                if dl_st == "COMPLETED" and pr_st == "COMPLETED":
                    s13_id = dr["source_document_id"]
                    if s13_id in ev_doc_ids:
                        print(f"      -> USEFUL (S13 ID={s13_id})")
                        useful_docs.append(d_item)
                    else:
                        print(f"      -> NON_USEFUL (S13 ID={s13_id})")
                        non_useful_docs.append(d_item)
                else:
                    print(f"      -> UNKNOWN (DL/Parse not COMPLETED)")
                    unknown_docs.append(d_item)

            print(f"  Summary: useful={len(useful_docs)}, non_useful={len(non_useful_docs)}, unknown={len(unknown_docs)}")

finally:
    doc_conn.close()
    crm_conn.close()
