import os
import sys
from pathlib import Path

# Add daemon's pythonpath
sys.path.insert(0, "/opt/tender_documents_research")

from dotenv import load_dotenv
load_dotenv(dotenv_path="/opt/tender_documents_research/.env")
load_dotenv(dotenv_path="/opt/tender_documents_research/database_work/db_credintials.env")

# Also load from /etc/tender-docs-worker.env using load_dotenv if it exists
if os.path.exists("/etc/tender-docs-worker.env"):
    load_dotenv(dotenv_path="/etc/tender-docs-worker.env")

import psycopg2

def run():
    host = os.getenv("DOCUMENT_DB_HOST", "127.0.0.1")
    port = int(os.getenv("DOCUMENT_DB_PORT", 5432))
    dbname = os.getenv("DOCUMENT_DB_NAME", "document_intelligence")
    user = os.getenv("DOCUMENT_DB_USER", "doc_worker")
    password = os.getenv("DOCUMENT_DB_PASSWORD", "")
    
    print(f"DOCUMENT_DB_HOST: {host}")
    print(f"DOCUMENT_DB_PORT: {port}")
    print(f"DOCUMENT_DB_NAME: {dbname}")
    print(f"DOCUMENT_DB_USER: {user}")
    print(f"DOCUMENT_DB_PASSWORD: {password}")
    
    try:
        conn = psycopg2.connect(
            host=host, port=port, database=dbname,
            user=user, password=password,
        )
        print("Successfully connected!")
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user;")
            print("Current database/user:", cur.fetchone())
            cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'document_processing_queue');")
            print("Has document_processing_queue:", cur.fetchone()[0])
        conn.close()
    except Exception as e:
        print("Failed to connect:", e)

if __name__ == "__main__":
    run()
