import os
import sys
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import (
    get_crm_db_connection,
)

crm_conn = get_crm_db_connection()
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT okpd_code, count(*)
        FROM crm_procurements
        GROUP BY okpd_code
        ORDER BY count(*) DESC
        LIMIT 30
    """)
    print("TOP 30 OKPD CODES in CRM:")
    for r in cur.fetchall():
        print(f"  {repr(r['okpd_code'])}: {r['count']}")

    cur.execute("""
        SELECT 
            count(*) as total,
            count(*) FILTER (WHERE okpd_code IS NULL) as null_count,
            count(*) FILTER (WHERE okpd_code = '') as empty_count,
            count(*) FILTER (WHERE okpd_code ~ '^[0-9]+(\.[0-9]+)*$') as standard_pattern,
            count(*) FILTER (WHERE okpd_code IS NOT NULL AND okpd_code != '' AND NOT (okpd_code ~ '^[0-9]+(\.[0-9]+)*$')) as non_standard
        FROM crm_procurements
    """)
    print("\nOKPD CODE PATTERNS:")
    for k, v in cur.fetchone().items():
        print(f"  {k}: {v}")
        
    cur.execute("""
        SELECT okpd_code, count(*)
        FROM crm_procurements
        WHERE okpd_code IS NOT NULL AND okpd_code != '' AND NOT (okpd_code ~ '^[0-9]+(\.[0-9]+)*$')
        GROUP BY okpd_code
        LIMIT 20
    """)
    print("\nSAMPLE NON-STANDARD OKPD CODES:")
    for r in cur.fetchall():
        print(f"  {repr(r['okpd_code'])}: {r['count']}")
