import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

doc_conn = psycopg2.connect(
    host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
    dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    password=os.getenv("S13_DOCUMENT_DB_PASSWORD", "")
)
crm_conn = psycopg2.connect(
    host=os.getenv("CRM_DB_HOST", "127.0.0.1"),
    port=int(os.getenv("CRM_DB_PORT", "5432")),
    dbname=os.getenv("CRM_DB_NAME", "crm"),
    user=os.getenv("CRM_DB_USER", "crm_app"),
    password=os.getenv("CRM_DB_PASSWORD", "")
)

doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

doc_cur.execute("""
    SELECT COUNT(*) as total_unknown, COUNT(DISTINCT procurement_id) as total_procs
    FROM document_match_details
    WHERE validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL
""")
row = doc_cur.fetchone()
print(f"UNKNOWN_DETAIL_ROWS_TOTAL={row['total_unknown']}")
print(f"UNKNOWN_TARGET_PROCUREMENTS={row['total_procs']}")

doc_cur.execute("""
    SELECT match_method, COUNT(*) as cnt
    FROM document_match_details
    WHERE validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR validation_status IS NULL
    GROUP BY match_method
    ORDER BY cnt DESC
""")
methods = doc_cur.fetchall()
print("UNKNOWN_BY_MATCH_METHOD:")
for m in methods:
    print(f"  {m['match_method']}: {m['cnt']}")

doc_conn.close()
crm_conn.close()
