import os
import sys
from pathlib import Path

# Add daemon's pythonpath
sys.path.insert(0, "/opt/tender_documents_research")

from dotenv import load_dotenv
load_dotenv(dotenv_path="/opt/tender_documents_research/.env")
load_dotenv(dotenv_path="/opt/tender_documents_research/database_work/db_credintials.env")

# Force correct password
os.environ["S13_DOCUMENT_DB_PASSWORD"] = "X17B3n5hbANQSRt6i7WIyy0lJudX"

from document_processor.backends.factory import create_processing_backend
backend = create_processing_backend("S13_V2")

print("Claiming tasks...")
tasks = backend.queue.claim_batch(worker_id=13, batch_size=1)
print("Claimed tasks:", tasks)
