#!/usr/bin/env python3
import sys
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
print("DOC_DB_HOST:", os.getenv("DOC_DB_HOST"))
print("DOC_DB_PORT:", os.getenv("DOC_DB_PORT"))
print("DOC_DB_NAME:", os.getenv("DOC_DB_NAME"))
print("DOC_DB_USER:", os.getenv("DOC_DB_USER"))

# Let's try connecting via TCP 127.0.0.1:5432 vs Unix Socket /var/run/postgresql
try:
    conn_tcp = psycopg2.connect(host="127.0.0.1", port=5432, dbname="document_intelligence", user="doc_worker", password=os.getenv("S13_DOCUMENT_DB_PASSWORD", "X17B3n5hbANQSRt6i7WIyy0lJudX"))
    with conn_tcp.cursor() as cur:
        cur.execute("SELECT count(*) FROM document_match_details WHERE validator_version = 'v4'")
        print("TCP 127.0.0.1 V4 count:", cur.fetchone()[0])
    conn_tcp.close()
except Exception as e:
    print("TCP Error:", e)

try:
    conn_sock = psycopg2.connect(dbname="document_intelligence", user="doc_worker", password=os.getenv("S13_DOCUMENT_DB_PASSWORD", "X17B3n5hbANQSRt6i7WIyy0lJudX"))
    with conn_sock.cursor() as cur:
        cur.execute("SELECT count(*) FROM document_match_details WHERE validator_version = 'v4'")
        print("Socket V4 count:", cur.fetchone()[0])
    conn_sock.close()
except Exception as e:
    print("Socket Error:", e)
