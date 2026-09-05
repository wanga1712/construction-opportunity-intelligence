import sys, os
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')

from src.services.commercial_routing_v3.learning_observer import LearningObserver
from src.services.commercial_routing_v3.shadow_predictor import ShadowPredictor

print("1. Running LearningObserver cycle 1...")
obs = LearningObserver()
res1 = obs.run_cycle()
print("OBSERVER CYCLE 1:", res1)

print("2. Running ShadowPredictor cycle 1...")
pred = ShadowPredictor()
res2 = pred.run_cycle()
print("PREDICTOR CYCLE 1:", res2)

print("3. Running ShadowPredictor cycle 2...")
res2_2 = pred.run_cycle()
print("PREDICTOR CYCLE 2:", res2_2)

print("4. Running ShadowPredictor cycle 3...")
res2_3 = pred.run_cycle()
print("PREDICTOR CYCLE 3:", res2_3)

print("5. Running LearningObserver cycle 2...")
res3 = obs.run_cycle()
print("OBSERVER CYCLE 2:", res3)
