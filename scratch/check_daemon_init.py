import os
import sys
from pathlib import Path

# Add daemon's pythonpath
sys.path.insert(0, "/opt/tender_documents_research")

from dotenv import load_dotenv
load_dotenv(dotenv_path="/opt/tender_documents_research/.env")
load_dotenv(dotenv_path="/opt/tender_documents_research/database_work/db_credintials.env")

# Force the worker.env environment
if os.path.exists("/etc/tender-docs-worker.env"):
    load_dotenv(dotenv_path="/etc/tender-docs-worker.env")

from document_processor.daemon import DocumentProcessorDaemon

daemon = DocumentProcessorDaemon()
print("Daemon s13_backend:", daemon.s13_backend)
if daemon.s13_backend:
    print("Daemon queue class:", daemon.s13_backend.queue.__class__)
    print("Daemon db alias for queue:", getattr(daemon.s13_backend.queue, "db_alias", None))
    print("Daemon db connections inside queue:", getattr(daemon.s13_backend.queue.db, "connections", None) if hasattr(daemon.s13_backend.queue, "db") else None)
