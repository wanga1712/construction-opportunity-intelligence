import os
import psycopg2
from src.services.db_bootstrap import connect_databases

def load_dotenv(path="/opt/CRM_Streamlit/.env"):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip()

def main():
    load_dotenv()
    _, _, crm_db, _ = connect_databases()
    if crm_db:
        print("TRACES FOR 900000800:")
        traces = crm_db.execute_query("SELECT id, attempt_count, consensus_state, research_completeness, document_set_hash, extracted_evidence_hash FROM crm_v3_autonomous_analysis_traces WHERE procurement_id = 900000800")
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
            print("QUEUE FOR 900000800:")
            cur.execute("SELECT id, procurement_id, pipeline_generation, status FROM document_processing_queue WHERE procurement_id = 900000800")
            for q in cur.fetchall():
                print(q)
        conn.close()
    except Exception as e:
        print("Error connecting/querying document DB:", e)

if __name__ == '__main__':
    main()
