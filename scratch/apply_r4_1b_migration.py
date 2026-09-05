#!/usr/bin/env python3
import sys
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

migration_sql_path = "/opt/CRM_Streamlit/src/migrations/crm_v4_structured_fact_schema_1b.sql"

with open(migration_sql_path, "r", encoding="utf-8") as f:
    sql_script = f.read()

statements = [stmt.strip() for stmt in sql_script.split(";") if stmt.strip()]

conn = get_doc_db_connection()
with conn.cursor() as cur:
    print(f"Executing {len(statements)} DDL statements for crm_v4_structured_fact_schema_1b.sql...")
    for idx, stmt in enumerate(statements, 1):
        print(f" Executing stmt {idx}/{len(statements)}...")
        cur.execute(stmt)
conn.commit()

with conn.cursor() as cur:
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'structured_entities'
          AND column_name IN ('quantity_raw', 'unit_price_raw', 'total_price_raw', 'currency_raw')
    """)
    cols = [r[0] for r in cur.fetchall()]
    print("Created/verified columns in structured_entities:", cols)
    assert len(cols) == 4, f"Expected 4 new raw columns, found {cols}"

conn.close()
print("R4 1b Migration applied successfully!")
