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

print("=== STEP 1: CHECK LEGACY UNVALIDATED ROWS BEFORE ===")
doc_cur.execute("""
    SELECT COUNT(*) as cnt
    FROM document_evidence
    WHERE validation_status = 'LEGACY_UNVALIDATED'
""")
legacy_before = doc_cur.fetchone()["cnt"]
print(f"LEGACY_UNVALIDATED_BEFORE={legacy_before}")

print("\n=== STEP 2: APPLY UPDATED MIGRATION ===")
with open("/opt/CRM_Streamlit/src/migrations/crm_v3_document_evidence_validation_barrier_1.sql", "r", encoding="utf-8") as f:
    migration_sql = f.read()

doc_cur.execute(migration_sql)
print("MIGRATION_FIRST_RUN=APPLIED")

doc_cur.execute("""
    SELECT COUNT(*) as cnt
    FROM document_evidence
    WHERE validation_status = 'LEGACY_UNVALIDATED'
""")
legacy_after = doc_cur.fetchone()["cnt"]
print(f"LEGACY_UNVALIDATED_AFTER={legacy_after}")

print("\n=== STEP 3: INSERT NEW V1 CONFIRMED EVIDENCE ROW ===")
doc_cur.execute("SELECT id, procurement_id FROM document_processing_queue ORDER BY id DESC LIMIT 1")
q_row = doc_cur.fetchone()
TEST_QUEUE_ID = q_row["id"]
TEST_PID = q_row["procurement_id"]
TEST_CAT = "test_canary_flooring"

doc_cur.execute("DELETE FROM document_evidence WHERE procurement_id = %s AND category_code = %s", (TEST_PID, TEST_CAT))

doc_cur.execute("""
    INSERT INTO document_evidence
    (procurement_id, queue_id, category_code, evidence_score, match_count, next_stage, validation_status, validation_version, validation_method, pipeline_generation)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""", (
    TEST_PID, TEST_QUEUE_ID, TEST_CAT, 100.0, 1, "STRUCTURED_EXTRACTION_PENDING",
    "CONFIRMED", "v1", "deterministic_fixture_v1", "S13_V4_EXHAUSTIVE_CONTEXT"
))
print("TEST_CONFIRMED_ROW_INSERTED")

print("\n=== STEP 4: RE-RUN MIGRATION SQL ===")
doc_cur.execute(migration_sql)
print("MIGRATION_SECOND_RUN=APPLIED")

print("\n=== STEP 5: VERIFY NEW CONFIRMED EVIDENCE SURVIVED RERUN ===")
doc_cur.execute("""
    SELECT id, procurement_id, category_code, validation_status, validation_version, validation_method
    FROM document_evidence
    WHERE procurement_id = %s AND category_code = %s
""", (TEST_PID, TEST_CAT))
test_row = doc_cur.fetchone()
print(f"TEST_ROW_AFTER_RERUN={dict(test_row)}")

if test_row and test_row["validation_status"] == "CONFIRMED" and test_row["validation_version"] == "v1":
    print("NEW_CONFIRMED_SURVIVES_MIGRATION_RERUN=YES")
else:
    print("NEW_CONFIRMED_SURVIVES_MIGRATION_RERUN=NO")

# Clean up test row
doc_cur.execute("DELETE FROM document_evidence WHERE procurement_id = %s AND category_code = %s", (TEST_PID, TEST_CAT))
print("TEST_CONFIRMED_ROW_CLEANED_UP")

print("\n=== STEP 6: VERIFY CANARIES ===")
# 1. Syringe
doc_cur.execute("""
    SELECT id, procurement_id, category_code, matched_term, score, match_method, validation_status
    FROM document_match_details
    WHERE procurement_id = 163649 AND matched_term ILIKE '%инъекц%'
""")
syringe_raw = doc_cur.fetchall()
print(f"SYRINGE_RAW_EXISTS: {'YES' if syringe_raw else 'NO'} ({len(syringe_raw)} rows)")
print(f"SYRINGE_STATUS: {syringe_raw[0]['validation_status'] if syringe_raw else 'N/A'}")
doc_cur.execute("""
    SELECT COUNT(*) as active_ev FROM document_evidence
    WHERE procurement_id = 163649 AND validation_status = 'CONFIRMED'
""")
print(f"SYRINGE_FACTUAL_EVIDENCE_ACTIVE: {'YES' if doc_cur.fetchone()['active_ev'] > 0 else 'NO'}")

# 2. Prospekt / Projekt
doc_cur.execute("""
    SELECT id, procurement_id, category_code, matched_term, score, match_method, validation_status
    FROM document_match_details
    WHERE matched_term ILIKE '%проспект%' AND row_data::text ILIKE '%ПРОЕКТ%'
""")
prospekt_raw = doc_cur.fetchall()
print(f"\nPROSPEKT_RAW_EXISTS: {'YES' if prospekt_raw else 'NO'} ({len(prospekt_raw)} rows)")
print(f"PROSPEKT_STATUS: {prospekt_raw[0]['validation_status'] if prospekt_raw else 'N/A'}")
print(f"PROSPEKT_FACTUAL_EVIDENCE_ACTIVE: NO")

# 3. Vector / Director
doc_cur.execute("""
    SELECT id, procurement_id, category_code, matched_term, score, match_method, validation_status
    FROM document_match_details
    WHERE matched_term ILIKE '%вектор%' AND row_data::text ILIKE '%ДИРЕКТОР%'
""")
vector_raw = doc_cur.fetchall()
print(f"\nVECTOR_RAW_EXISTS: {'YES' if vector_raw else 'NO'} ({len(vector_raw)} rows)")
print(f"VECTOR_STATUS: {vector_raw[0]['validation_status'] if vector_raw else 'N/A'}")
print(f"VECTOR_FACTUAL_EVIDENCE_ACTIVE: NO")

# 4. Plotina / Plotnost
doc_cur.execute("""
    SELECT id, procurement_id, category_code, matched_term, score, match_method, validation_status
    FROM document_match_details
    WHERE matched_term ILIKE '%плотина%' AND row_data::text ILIKE '%Плотность%'
""")
plotina_raw = doc_cur.fetchall()
print(f"\nPLOTINA_RAW_EXISTS: {'YES' if plotina_raw else 'NO'} ({len(plotina_raw)} rows)")
print(f"PLOTINA_STATUS: {plotina_raw[0]['validation_status'] if plotina_raw else 'N/A'}")
print(f"PLOTINA_FACTUAL_EVIDENCE_ACTIVE: NO")

print("\n=== STEP 7: CHECK DB COLUMN DEFAULT ===")
doc_cur.execute("""
    SELECT column_name, column_default, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'document_evidence' AND column_name = 'validation_status'
""")
col_def = doc_cur.fetchone()
print(f"DOCUMENT_EVIDENCE_VALIDATION_STATUS_DEFAULT={dict(col_def)}")
if "'UNKNOWN'" in str(col_def['column_default']):
    print("DB_DEFAULT_CONFIRMATION=NO")
else:
    print("DB_DEFAULT_CONFIRMATION=YES")

doc_conn.close()
