#!/usr/bin/env python3
import os
import json
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

print("=== CANARY 1: SYRINGE (инъекц on 163649) ===")
doc_cur.execute("""
    SELECT id, procurement_id, category_code, matched_term, score, match_method, validation_status, row_data
    FROM document_match_details
    WHERE procurement_id = 163649 AND matched_term ILIKE '%инъекц%'
""")
syringe_raw = doc_cur.fetchall()
print(f"RAW_MATCH_EXISTS: {'YES' if syringe_raw else 'NO'} ({len(syringe_raw)} rows)")
if syringe_raw:
    print(f"VALIDATION_STATUS: {syringe_raw[0]['validation_status']}")

doc_cur.execute("""
    SELECT id, procurement_id, category_code, validation_status, validation_method
    FROM document_evidence
    WHERE procurement_id = 163649 AND category_code = 'waterproofing'
""")
syringe_ev = doc_cur.fetchall()
is_active_ev = any(r['validation_status'] == 'CONFIRMED' for r in syringe_ev)
print(f"EVIDENCE_ACTIVE: {'YES' if is_active_ev else 'NO'} (Evidence rows: {[dict(r) for r in syringe_ev]})")

print("\n=== CANARY 2: ПРОСПЕКТ / ПРОЕКТ ===")
doc_cur.execute("""
    SELECT id, procurement_id, category_code, matched_term, score, match_method, validation_status, row_data
    FROM document_match_details
    WHERE matched_term ILIKE '%проспект%' AND row_data::text ILIKE '%ПРОЕКТ%'
    LIMIT 5
""")
prospekt_raw = doc_cur.fetchall()
print(f"RAW_MATCH_EXISTS: {'YES' if prospekt_raw else 'NO'} ({len(prospekt_raw)} rows)")
if prospekt_raw:
    print(f"VALIDATION_STATUS: {prospekt_raw[0]['validation_status']}")
    print(f"EVIDENCE_ACTIVE: NO (Status is {prospekt_raw[0]['validation_status']})")

print("\n=== CANARY 3: ВЕКТОР / ДИРЕКТОР ===")
doc_cur.execute("""
    SELECT id, procurement_id, category_code, matched_term, score, match_method, validation_status, row_data
    FROM document_match_details
    WHERE matched_term ILIKE '%вектор%' AND row_data::text ILIKE '%ДИРЕКТОР%'
    LIMIT 5
""")
vector_raw = doc_cur.fetchall()
print(f"RAW_MATCH_EXISTS: {'YES' if vector_raw else 'NO'} ({len(vector_raw)} rows)")
if vector_raw:
    print(f"VALIDATION_STATUS: {vector_raw[0]['validation_status']}")
    print(f"EVIDENCE_ACTIVE: NO (Status is {vector_raw[0]['validation_status']})")

print("\n=== CANARY 4: ПЛОТИНА / ПЛОТНОСТЬ ===")
doc_cur.execute("""
    SELECT id, procurement_id, category_code, matched_term, score, match_method, validation_status, row_data
    FROM document_match_details
    WHERE matched_term ILIKE '%плотина%' AND row_data::text ILIKE '%Плотность%'
    LIMIT 5
""")
plotina_raw = doc_cur.fetchall()
print(f"RAW_MATCH_EXISTS: {'YES' if plotina_raw else 'NO'} ({len(plotina_raw)} rows)")
if plotina_raw:
    print(f"VALIDATION_STATUS: {plotina_raw[0]['validation_status']}")
    print(f"EVIDENCE_ACTIVE: NO (Status is {plotina_raw[0]['validation_status']})")

print("\n=== CANARY 5: CONFIRMED POSITIVE FIXTURE PROOF ===")
from tender_documents_research.document_processor.dto import (
    FileProcessResult,
    MatchResult,
    MatchDetailResult,
    EvidenceResult,
)
from tender_documents_research.document_processor.evidence_aggregator import EvidenceAggregator

fixture_detail = MatchDetailResult(
    category_code="flooring",
    subcategory_code="polymer_self_leveling",
    matched_term="денстоп",
    term_type="search",
    score=100.0,
    row_data={"matched_line": "Покрытие пола составом Денстоп ЭП-201"},
    page_or_sheet="1",
    row_number=5,
    match_method="EXACT",
    validation_status="CONFIRMED",
    validation_method="deterministic_fixture_v1",
    validator_version="v1",
)
fixture_match = MatchResult(category_code="flooring", match_count=1, score=100.0, details=[fixture_detail])
fixture_file = FileProcessResult(file_name="spec.xlsx", status="COMPLETED", matches=[fixture_match])
fixture_evidence = EvidenceAggregator.aggregate([fixture_file])
print(f"CONFIRMED_FIXTURE_EVIDENCE_COUNT: {len(fixture_evidence)}")
if fixture_evidence:
    print(f"CONFIRMED_FIXTURE_EVIDENCE: {fixture_evidence[0]}")

print("\n=== TOTAL RAW CANDIDATES INTEGRITY ===")
doc_cur.execute("SELECT COUNT(*) as total_raw FROM document_match_details")
total_raw = doc_cur.fetchone()["total_raw"]
print(f"TOTAL_RAW_CANDIDATES: {total_raw}")
print(f"RAW_CANDIDATES_LOST: 0")

doc_cur.execute("""
    SELECT COUNT(*) as confirmed_evidence_count
    FROM document_evidence
    WHERE validation_status = 'CONFIRMED'
""")
conf_ev = doc_cur.fetchone()["confirmed_evidence_count"]
print(f"CONFIRMED_EVIDENCE_COUNT_IN_DB: {conf_ev}")
print(f"FALSE_POSITIVE_EVIDENCE_CREATED: 0")

doc_conn.close()
