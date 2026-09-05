import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

conn = psycopg2.connect(
    host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
    dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    password=os.getenv("S13_DOCUMENT_DB_PASSWORD", "")
)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'document_matches'")
print('document_matches:', [r['column_name'] for r in cur.fetchall()])
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'document_match_details'")
print('document_match_details:', [r['column_name'] for r in cur.fetchall()])
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'document_processing_queue'")
print('document_processing_queue:', [r['column_name'] for r in cur.fetchall()])
conn.close()
