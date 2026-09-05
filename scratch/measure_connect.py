import time
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")
from src.services.db_bootstrap import connect_databases

print("Measuring connect_databases...")
t0 = time.time()
res = connect_databases()
t1 = time.time()
print(f"connect_databases took {t1 - t0:.4f} seconds")
if res[3]:
    print(f"Warning/Error message: {res[3]}")
