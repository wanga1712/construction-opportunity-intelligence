#!/usr/bin/env python3
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

doc_dsn = {
    "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
    "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
}

doc_conn = psycopg2.connect(**doc_dsn)
doc_conn.autocommit = True
doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("=== 1. ADD VALIDATION AND METHOD COLUMNS TO document_match_details ===")
match_detail_columns = [
    ("match_method", "VARCHAR(50) DEFAULT 'UNKNOWN'"),
    ("validation_status", "VARCHAR(30) DEFAULT 'UNKNOWN'"),
    ("validation_method", "VARCHAR(50) DEFAULT NULL"),
    ("validation_reason", "TEXT DEFAULT NULL"),
    ("validated_at", "TIMESTAMP WITH TIME ZONE DEFAULT NULL"),
    ("validator_name", "VARCHAR(100) DEFAULT NULL"),
    ("validator_version", "VARCHAR(50) DEFAULT NULL"),
]

for col, col_type in match_detail_columns:
    try:
        doc_cur.execute(f"ALTER TABLE document_match_details ADD COLUMN IF NOT EXISTS {col} {col_type}")
        print(f"Added column {col} to document_match_details")
    except Exception as e:
        print(f"Column {col} already exists or error: {e}")

print("\n=== 2. ADD VALIDATION COLUMNS TO document_evidence ===")
evidence_columns = [
    ("validation_status", "VARCHAR(30) DEFAULT 'CONFIRMED'"),
    ("validation_version", "VARCHAR(50) DEFAULT 'v1'"),
    ("validation_method", "VARCHAR(50) DEFAULT NULL"),
]

for col, col_type in evidence_columns:
    try:
        doc_cur.execute(f"ALTER TABLE document_evidence ADD COLUMN IF NOT EXISTS {col} {col_type}")
        print(f"Added column {col} to document_evidence")
    except Exception as e:
        print(f"Column {col} already exists or error: {e}")

print("\n=== 3. MARK UNVALIDATED LEGACY EVIDENCE ===")
doc_cur.execute("""
    UPDATE document_evidence
    SET validation_status = 'LEGACY_UNVALIDATED',
        validation_method = 'legacy_pre_r3_3'
    WHERE validation_status IS NULL OR validation_status = 'CONFIRMED'
""")
print(f"Updated {doc_cur.rowcount} legacy document_evidence rows to LEGACY_UNVALIDATED")

print("\n=== 4. DEFAULT HISTORICAL document_match_details TO UNKNOWN ===")
doc_cur.execute("""
    UPDATE document_match_details
    SET validation_status = 'UNKNOWN',
        match_method = COALESCE(match_method, 'UNKNOWN')
    WHERE validation_status IS NULL
""")
print(f"Updated {doc_cur.rowcount} historical document_match_details rows to UNKNOWN")

print("\n=== 5. CHECK SYRINGE ROW 163649 IN document_evidence ===")
doc_cur.execute("""
    SELECT id, procurement_id, category_code, evidence_score, match_count, validation_status, validation_method
    FROM document_evidence
    WHERE procurement_id = 163649
""")
for r in doc_cur.fetchall():
    print("SYRINGE EVIDENCE ROW:", dict(r))

doc_conn.close()
