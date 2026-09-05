#!/usr/bin/env python3
import sys
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

migration_sql_path = "/opt/CRM_Streamlit/src/migrations/crm_v4_structured_fact_schema_1.sql"

with open(migration_sql_path, "r", encoding="utf-8") as f:
    sql_script = f.read()

# Split by ';' to ensure every statement executes cleanly
statements = [stmt.strip() for stmt in sql_script.split(";") if stmt.strip()]

conn = get_doc_db_connection()
with conn.cursor() as cur:
    print(f"Executing {len(statements)} DDL statements...")
    for idx, stmt in enumerate(statements, 1):
        print(f" Executing stmt {idx}/{len(statements)}...")
        cur.execute(stmt)
conn.commit()

with conn.cursor() as cur:
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_name IN ('structured_extraction_runs', 'structured_entities', 'structured_attributes')
    """)
    tables = [r[0] for r in cur.fetchall()]
    print("Created/verified R4 tables:", tables)
    assert len(tables) == 3, f"Expected 3 R4 tables, found {tables}"

conn.close()
print("R4 Migration applied successfully!")
