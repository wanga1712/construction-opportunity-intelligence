import os
import sys
from pathlib import Path

# Add daemon's pythonpath
sys.path.insert(0, "/opt/tender_documents_research")

from dotenv import load_dotenv
load_dotenv(dotenv_path="/opt/tender_documents_research/.env")
load_dotenv(dotenv_path="/opt/tender_documents_research/database_work/db_credintials.env")

# Mimic systemd environment
os.environ["PROCESSING_BACKEND"] = "S13_V2"
os.environ["S13_DOCUMENT_DB_USER"] = "crm_app"
os.environ["S13_DOCUMENT_DB_PASSWORD"] = "X17B3n5hbANQSRt6i7WIyy0lJudX"

from database_work.database_connection import DatabaseManager

def run():
    db_configs = {
        'tender_monitor': {
            'host': os.getenv("DB_HOST_TENDER"),
            'name': os.getenv("DB_DATABASE_TENDER"),
            'user': os.getenv("DB_USER_TENDER"),
            'password': os.getenv("DB_PASSWORD_TENDER"),
            'port': os.getenv("DB_PORT_TENDER"),
        },
        'document_intelligence': {
            'host': os.getenv("S13_DOCUMENT_DB_HOST", "localhost"),
            'name': os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
            'user': os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
            'password': os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
            'port': os.getenv("S13_DOCUMENT_DB_PORT", "5432"),
        }
    }
    
    db = DatabaseManager(db_configs)
    for alias, conn in db.connections.items():
        print(f"Alias: {alias}")
        print(f"  DSN: {conn.dsn}")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user;")
                res = cur.fetchone()
                print(f"  Current DB/User: {res}")
                cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'document_processing_queue');")
                has_table = cur.fetchone()[0]
                print(f"  Has document_processing_queue: {has_table}")
        except Exception as e:
            print(f"  Error: {e}")
            conn.rollback()

if __name__ == "__main__":
    run()
