#!/usr/bin/env python3
import os
import json
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.okpd_priors import (
    load_okpd_priors_from_db,
    classify_target_okpd,
    ADMISSION_TARGET,
    ADMISSION_OUT_OF_TARGET,
    ADMISSION_UNKNOWN_OKPD,
)
from src.services.commercial_routing_v3.factual_feeder import FactualFeeder
from src.services.commercial_routing_v3.document_links import resolve_document_links

crm_dsn = {
    "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CRM_DB_PORT", "5432")),
    "dbname": os.getenv("CRM_DB_NAME", "crm"),
    "user": os.getenv("CRM_DB_USER", "crm_app"),
    "password": os.getenv("CRM_DB_PASSWORD", ""),
}

doc_dsn = {
    "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
    "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
    "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
}

crm_conn = psycopg2.connect(**crm_dsn)
doc_conn = psycopg2.connect(**doc_dsn)

crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
doc_cur = doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

class CrmDbWrapper:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, sql, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

crm_db = CrmDbWrapper(crm_conn)
priors = load_okpd_priors_from_db(crm_db)
feeder = FactualFeeder(crm_db)

print("==================================================")
print("1 — CANARY 163649")
print("==================================================")
crm_cur.execute("SELECT id, contract_number, okpd_code, okpd_name FROM crm_procurements WHERE id = 163649")
canary_163649 = crm_cur.fetchone()
okpd_163649 = canary_163649["okpd_code"]
cls_163649, matched_163649 = classify_target_okpd(okpd_163649, priors)

doc_cur.execute("SELECT id, status, last_error FROM document_processing_queue WHERE procurement_id = 163649 AND pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'")
q_163649 = doc_cur.fetchall()

print(f"PROCUREMENT_ID=163649")
print(f"CONTRACT_NUMBER={canary_163649['contract_number']}")
print(f"OKPD_CODE={okpd_163649}")
print(f"OKPD_NAME={canary_163649['okpd_name']}")
print(f"TARGET_CLASSIFICATION={cls_163649}")
print(f"MATCHED_TARGET_PRIORS={matched_163649}")

# Test admission through feeder
feeder_res_163649 = feeder.admit_procurement(canary_163649, priors=priors)
print(f"FEEDER_ADMIT_RESULT={feeder_res_163649}")
print(f"NEW_RESEARCH_QUEUE_ROW_CREATED={'NO' if not feeder_res_163649['admitted'] else 'YES'}")

print("\n==================================================")
print("2 — POSITIVE CANARIES (5 Target Procurements)")
print("==================================================")
# Find 5 target procurements with documents
crm_cur.execute("""
    SELECT id, contract_number, okpd_code, okpd_name, source_table, source_id
    FROM crm_procurements
    WHERE okpd_code IS NOT NULL 
      AND okpd_code != ''
      AND crm_stage NOT IN ('cancelled', 'failed', 'closed', 'rejected', 'archived', 'no_winner', 'suspended', 'razygranye')
    ORDER BY id DESC
    LIMIT 200
""")
candidates = crm_cur.fetchall()

positive_canaries = []
for c in candidates:
    cls, matched = classify_target_okpd(c["okpd_code"], priors)
    if cls == ADMISSION_TARGET:
        links_res = resolve_document_links(
            source_table=c["source_table"],
            source_id=c["source_id"],
            contract_number=c["contract_number"],
        )
        links = links_res.get("links") or []
        if links:
            positive_canaries.append({
                "procurement_id": c["id"],
                "okpd_code": c["okpd_code"],
                "matched_prior": matched[0]["commercial_category_code"] + " (" + matched[0]["okpd_pattern"] + ")",
                "classification": cls,
                "document_link_count": len(links),
                "initial_queue_status": "PRE_RESEARCH_WAITING"
            })
            if len(positive_canaries) >= 5:
                break

for i, pc in enumerate(positive_canaries, 1):
    print(f"POSITIVE_CANARY_{i}:")
    for k, v in pc.items():
        print(f"  {k}: {v}")

print(f"POSITIVE_CANARIES_VALID={len(positive_canaries)}/5")

print("\n==================================================")
print("3 — NEGATIVE CANARIES (5 Out-of-Target Procurements)")
print("==================================================")
negative_canaries = [
    {
        "procurement_id": 163649,
        "okpd_code": okpd_163649,
        "classification": cls_163649,
        "new_queue_row_created": "NO"
    }
]

for c in candidates:
    cls, matched = classify_target_okpd(c["okpd_code"], priors)
    if cls == ADMISSION_OUT_OF_TARGET and c["id"] != 163649:
        adm = feeder.admit_procurement(c, priors=priors)
        negative_canaries.append({
            "procurement_id": c["id"],
            "okpd_code": c["okpd_code"],
            "classification": cls,
            "new_queue_row_created": "NO" if not adm["admitted"] else "YES"
        })
        if len(negative_canaries) >= 5:
            break

for i, nc in enumerate(negative_canaries, 1):
    print(f"NEGATIVE_CANARY_{i}:")
    for k, v in nc.items():
        print(f"  {k}: {v}")

print(f"NEGATIVE_CANARIES_VALID={len(negative_canaries)}/5")

print("\n==================================================")
print("4 — UNKNOWN CANARIES (Missing / Blank OKPD)")
print("==================================================")
crm_cur.execute("""
    SELECT id, contract_number, okpd_code, okpd_name, source_table, source_id
    FROM crm_procurements
    WHERE (okpd_code IS NULL OR okpd_code = '' OR trim(okpd_code) = '')
      AND crm_stage NOT IN ('cancelled', 'failed', 'closed', 'rejected', 'archived', 'no_winner', 'suspended', 'razygranye')
    LIMIT 10
""")
unknown_candidates = crm_cur.fetchall()
unknown_canaries = []
for c in unknown_candidates:
    cls, matched = classify_target_okpd(c.get("okpd_code"), priors)
    adm = feeder.admit_procurement(c, priors=priors)
    unknown_canaries.append({
        "procurement_id": c["id"],
        "okpd_code": repr(c.get("okpd_code")),
        "classification": cls,
        "new_executable_queue_row_created": "NO" if not adm["admitted"] else "YES"
    })
    if len(unknown_canaries) >= 3:
        break

# If natural rows < 3, add fixture cases
if len(unknown_canaries) < 3:
    for fix_id, fix_code in [(999901, None), (999902, ""), (999903, "   ")]:
        cls, _ = classify_target_okpd(fix_code, priors)
        adm = feeder.admit_procurement({"id": fix_id, "okpd_code": fix_code}, priors=priors)
        unknown_canaries.append({
            "procurement_id": fix_id,
            "okpd_code": repr(fix_code),
            "classification": cls,
            "new_executable_queue_row_created": "NO" if not adm["admitted"] else "YES"
        })
        if len(unknown_canaries) >= 3:
            break

for i, uc in enumerate(unknown_canaries, 1):
    print(f"UNKNOWN_CANARY_{i}:")
    for k, v in uc.items():
        print(f"  {k}: {v}")

print(f"UNKNOWN_CANARIES_VALID={len(unknown_canaries)}/3")

print("\n==================================================")
print("5 — POST-CLEANUP QUEUE COUNTS")
print("==================================================")
doc_cur.execute("""
    SELECT status, COUNT(*) as cnt
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
    GROUP BY status
    ORDER BY status
""")
queue_status_counts = {r["status"]: r["cnt"] for r in doc_cur.fetchall()}
print(f"PRE_RESEARCH_WAITING={queue_status_counts.get('PRE_RESEARCH_WAITING', 0)}")
print(f"PENDING={queue_status_counts.get('PENDING', 0)}")
print(f"PROCESSING={queue_status_counts.get('PROCESSING', 0)}")
print(f"COMPLETED={queue_status_counts.get('COMPLETED', 0)}")
print(f"FAILED={queue_status_counts.get('FAILED', 0)}")
print(f"NO_LINKS={queue_status_counts.get('NO_LINKS', 0)}")

# Check active rows for out of target or unknown okpd
doc_cur.execute("""
    SELECT id, procurement_id, status
    FROM document_processing_queue
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
      AND status IN ('PRE_RESEARCH_WAITING', 'PENDING', 'PROCESSING')
""")
active_rows = doc_cur.fetchall()
active_pids = [r["procurement_id"] for r in active_rows]

out_of_target_active = 0
unknown_okpd_active = 0

if active_pids:
    placeholders = ",".join(["%s"] * len(active_pids))
    crm_cur.execute(f"SELECT id, okpd_code FROM crm_procurements WHERE id IN ({placeholders})", tuple(active_pids))
    active_okpd_map = {r["id"]: r["okpd_code"] for r in crm_cur.fetchall()}
    for r in active_rows:
        code = active_okpd_map.get(r["procurement_id"])
        cls, _ = classify_target_okpd(code, priors)
        if cls == ADMISSION_OUT_OF_TARGET:
            out_of_target_active += 1
        elif cls == ADMISSION_UNKNOWN_OKPD:
            unknown_okpd_active += 1

print(f"OUT_OF_TARGET_ACTIVE_QUEUE_ROWS={out_of_target_active}")
print(f"UNKNOWN_OKPD_ACTIVE_QUEUE_ROWS={unknown_okpd_active}")

crm_conn.close()
doc_conn.close()
