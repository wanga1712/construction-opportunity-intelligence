import sys
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

conn = get_doc_db_connection()

with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT COUNT(*)
        FROM document_match_details
        WHERE validated_at >= '2026-09-02 15:20:00+03'
    """)
    val_count = cur.fetchone()["count"]

    cur.execute("""
        SELECT validation_status, validation_reason, validated_at, id
        FROM document_match_details
        WHERE validated_at >= '2026-09-02 15:20:00+03'
        ORDER BY validated_at DESC
        LIMIT 10
    """)
    recent = cur.fetchall()

print(f"NEWLY_VALIDATED_COUNT: {val_count}")
for r in recent:
    print(f"ID {r['id']}: status={r['validation_status']}, reason={r['validation_reason']}, validated_at={r['validated_at']}")

conn.close()
