#!/usr/bin/env python3
import sys
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
sys.path.insert(0, ".")

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection

doc_conn = get_doc_db_connection()
print("DSN Params:", doc_conn.get_dsn_parameters())
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT current_database(), current_user, inet_server_addr(), inet_server_port()")
    print("DB Session info:", cur.fetchone())

    cur.execute("SELECT id, validator_version, pipeline_generation, validated_at FROM document_match_details WHERE validator_version = 'v4'")
    rows = [dict(r) for r in cur.fetchall()]
    print("V4 rows count:", len(rows))
