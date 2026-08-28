import os
import psycopg2
from src.services.db_bootstrap import connect_databases

def main():
    _, _, crm_db, _ = connect_databases()
    if crm_db:
        print("TRACES:")
        traces = crm_db.execute_query("SELECT id, attempt_count, consensus_state, research_completeness, document_set_hash, extracted_evidence_hash FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 900000700")
        for tr in traces:
            print(tr)

    # Connect to document DB
    host = os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1")
    port = int(os.getenv("S13_DOCUMENT_DB_PORT", "5432"))
    dbname = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    user = os.getenv("S13_DOCUMENT_DB_USER", "doc_worker")
    pwd = os.getenv("S13_DOCUMENT_DB_PASSWORD", "")
    
    try:
        conn = psycopg2.connect(host=host, port=port, user=user, password=pwd, database=dbname)
        with conn.cursor() as cur:
            print("QUEUE:")
            cur.execute("SELECT id, procurement_id, pipeline_generation, status FROM document_processing_queue WHERE procurement_id = 900000700")
            for q in cur.fetchall():
                print(q)
            print("FILES:")
            cur.execute("SELECT id, file_name, download_status, url, url_hash FROM document_files WHERE procurement_id = 900000700")
            for f in cur.fetchall():
                print(f)
        conn.close()
    except Exception as e:
        print("Error connecting/querying document DB:", e)

if __name__ == '__main__':
    main()
