import os
import hashlib
import psycopg2
import json

def load_dotenv():
    env_path = "/opt/CRM_Streamlit/.env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    parts = line.split("=", 1)
                    k = parts[0].strip()
                    v = parts[1].strip().strip("'\"")
                    os.environ[k] = v

def compute_sha256(val) -> str:
    s = str(val or "")
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def get_crm_db():
    user = os.environ.get("CRM_DB_USER", "crm_app")
    password = os.environ.get("CRM_DB_PASSWORD")
    host = os.environ.get("CRM_DB_HOST", "127.0.0.1")
    port = os.environ.get("CRM_DB_PORT", "5432")
    return psycopg2.connect(dbname="crm", user=user, password=password, host=host, port=port)

def get_doc_db():
    user = os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker")
    password = os.environ.get("S13_DOCUMENT_DB_PASSWORD")
    host = os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1")
    port = os.environ.get("S13_DOCUMENT_DB_PORT", "5432")
    return psycopg2.connect(dbname="document_intelligence", user=user, password=password, host=host, port=port)

def main():
    load_dotenv()
    doc_conn = get_doc_db()
    crm_conn = get_crm_db()
    try:
        doc_cur = doc_conn.cursor()
        crm_cur = crm_conn.cursor()
        
        doc_cur.execute("""
            SELECT id, procurement_id, pipeline_generation, research_generation_hash, created_at, completed_at, category_context
            FROM document_processing_queue
            WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
              AND category_context::text LIKE '%ONLINE_CLEAN%'
            LIMIT 10
        """)
        rows = doc_cur.fetchall()
        print(f"ONLINE_CLEAN rows count: {len(rows)}")
        for q_id, pid, gen, g_hash, q_created, q_completed, cat_ctx in rows:
            print(f"--- q_id={q_id}, pid={pid}, hash={g_hash} ---")
            
            effective_gen_hash = g_hash or compute_sha256(pid)
            
            crm_cur.execute("""
                SELECT created_at FROM crm_v3_pre_research_snapshots
                WHERE procurement_id = %s AND research_generation_hash = %s AND pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
            """, (pid, effective_gen_hash))
            snap_res = crm_cur.fetchone()
            snap_created = snap_res[0] if snap_res else None
            
            crm_cur.execute("""
                SELECT created_at FROM crm_v3_shadow_predictions
                WHERE procurement_id = %s AND research_generation_hash = %s
            """, (pid, effective_gen_hash))
            pred_res = crm_cur.fetchone()
            pred_at = pred_res[0] if pred_res else None
            
            doc_cur.execute("""
                SELECT MIN(downloaded_at) FROM document_files WHERE procurement_id = %s
            """, (pid,))
            dl_res = doc_cur.fetchone()
            dl_at = dl_res[0] if dl_res else None
            
            doc_cur.execute("""
                SELECT MIN(completed_at) FROM document_processing_results r
                JOIN document_files f ON f.id = r.file_id
                WHERE f.procurement_id = %s
            """, (pid,))
            parse_res = doc_cur.fetchone()
            parse_at = parse_res[0] if parse_res else None
            
            print(f"  QUEUE_CREATED_AT={q_created}")
            print(f"  SNAPSHOT_CREATED_AT={snap_created}")
            print(f"  BLIND_PREDICTION_AT={pred_at}")
            print(f"  QUEUE_RELEASED_AT={pred_at}")
            print(f"  FIRST_DOWNLOAD_AT={dl_at}")
            print(f"  FIRST_PARSED_AT={parse_at}")
            
    finally:
        doc_conn.close()
        crm_conn.close()

if __name__ == "__main__":
    main()
