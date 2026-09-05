#!/usr/bin/env python3
import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

crm_dsn = {
    "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CRM_DB_PORT", "5432")),
    "dbname": os.getenv("CRM_DB_NAME", "crm"),
    "user": os.getenv("CRM_DB_USER", "crm_app"),
    "password": os.getenv("CRM_DB_PASSWORD", ""),
}

conn = psycopg2.connect(**crm_dsn)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("=== 1. SAMPLE 10 CANDIDATE_SIGNAL PRIORS ===")
cur.execute("""
    SELECT okpd_pattern, commercial_category_code as category, signal_role as role, prior_kind as kind, provenance, match_type
    FROM crm_category_okpd_priors
    WHERE active = TRUE AND signal_role = 'CANDIDATE_SIGNAL'
    LIMIT 10
""")
cand_sample = cur.fetchall()
for i, r in enumerate(cand_sample, 1):
    print(f"CANDIDATE_SIGNAL_{i}: {dict(r)}")

print("\n=== 2. SAMPLE 10 CONTEXTUAL_RESEARCH PRIORS ===")
cur.execute("""
    SELECT okpd_pattern, commercial_category_code as category, signal_role as role, prior_kind as kind, provenance, match_type
    FROM crm_category_okpd_priors
    WHERE active = TRUE AND signal_role = 'CONTEXTUAL_RESEARCH'
    LIMIT 10
""")
ctx_sample = cur.fetchall()
for i, r in enumerate(ctx_sample, 1):
    print(f"CONTEXTUAL_RESEARCH_{i}: {dict(r)}")

conn.close()
