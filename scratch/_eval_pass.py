import sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')

from src.services.commercial_routing_v3.learning_observer import LearningObserver

obs = LearningObserver()
res = obs.run_cycle()
print("EVALUATION & EXAMPLE GENERATION:", res)
