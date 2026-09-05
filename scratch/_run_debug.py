import sys, os, json
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')

os.environ["CRM_DB_USER"] = "crm_app"
os.environ["CRM_DB_PASSWORD"] = "X17B3n5hbANQSRt6i7WIyy0lJudX"
os.environ["S13_DOCUMENT_DB_USER"] = "doc_worker"
os.environ["S13_DOCUMENT_DB_PASSWORD"] = "F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT"

from src.services.commercial_routing_v3.learning_observer import LearningObserver
from src.services.commercial_routing_v3.shadow_predictor import ShadowPredictor

print("1. Running Observer...")
obs = LearningObserver()
res1 = obs.run_cycle()
print("OBSERVER RESULT:", res1)

print("2. Running Predictor...")
pred = ShadowPredictor()
res2 = pred.run_cycle()
print("PREDICTOR RESULT 1:", res2)

res2_2 = pred.run_cycle()
print("PREDICTOR RESULT 2:", res2_2)

res2_3 = pred.run_cycle()
print("PREDICTOR RESULT 3:", res2_3)

print("3. Running Observer second pass...")
res3 = obs.run_cycle()
print("OBSERVER SECOND PASS:", res3)
