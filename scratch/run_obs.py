import os
import sys

os.environ["CRM_DB_USER"] = "crm_app"
os.environ["CRM_DB_PASSWORD"] = "X17B3n5hbANQSRt6i7WIyy0lJudX"
os.environ["CRM_DB_HOST"] = "127.0.0.1"
os.environ["CRM_DB_PORT"] = "5432"
os.environ["S13_DOCUMENT_DB_USER"] = "doc_worker"
os.environ["S13_DOCUMENT_DB_PASSWORD"] = "F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT"
os.environ["S13_DOCUMENT_DB_HOST"] = "127.0.0.1"
os.environ["S13_DOCUMENT_DB_PORT"] = "5432"

sys.path.append("/opt/CRM_Streamlit_rescue")
sys.path.append("/opt/pythonProject89")

import logging
logging.basicConfig(level=logging.INFO)

from src.services.commercial_routing_v3.learning_observer import LearningObserver
observer = LearningObserver()

print("Running snapshot builder...")
snap_cnt = observer._build_missing_snapshots()
print(f"Pre-research snapshots created: {snap_cnt}")

print("Running truths builder...")
truth_cnt = observer._build_missing_truths()
print(f"Exhaustive truths created: {truth_cnt}")
