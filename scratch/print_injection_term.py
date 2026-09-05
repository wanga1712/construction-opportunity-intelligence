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

crm_conn = psycopg2.connect(**crm_dsn)
crm_cur = crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

crm_cur.execute("""
    SELECT t.*, s.subcategory_code, c.category_code
    FROM crm_product_subcategory_terms t
    JOIN crm_product_subcategories s ON s.id = t.subcategory_id
    JOIN crm_product_categories c ON c.id = s.category_id
    WHERE t.phrase ILIKE '%инъекц%'
""")
for r in crm_cur.fetchall():
    print(json.dumps(dict(r), ensure_ascii=False, indent=2, default=str))

crm_conn.close()
