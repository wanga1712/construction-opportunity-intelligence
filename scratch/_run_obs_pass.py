import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')

os.environ["CRM_DB_USER"] = "crm_app"
os.environ["CRM_DB_PASSWORD"] = "X17B3n5hbANQSRt6i7WIyy0lJudX"
os.environ["S13_DOCUMENT_DB_USER"] = "doc_worker"
os.environ["S13_DOCUMENT_DB_PASSWORD"] = "F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT"

from src.services.commercial_routing_v3.learning_observer import LearningObserver

obs = LearningObserver()
res = obs.run_cycle()
print("OBSERVER CYCLE RESULT:", res)
