#!/usr/bin/env python3
import sys
import os
import psycopg2

sys.path.insert(0, ".")
from tender_documents_research.document_processor.context_validator_service import get_crm_db_connection

crm_conn = get_crm_db_connection()
with crm_conn.cursor() as cur:
    try:
        cur.execute("SELECT count(*) FROM crm_procurements")
        print("crm_procurements count:", cur.fetchone()[0])
    except Exception as e:
        print("crm_procurements error:", e)

crm_conn = get_crm_db_connection()
with crm_conn.cursor() as cur:
    try:
        cur.execute("SELECT count(*) FROM procurements")
        print("procurements count:", cur.fetchone()[0])
    except Exception as e:
        print("procurements error:", e)
