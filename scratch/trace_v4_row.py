import os
import psycopg2

def load_dotenv():
    env_path = "/opt/CRM_Streamlit/.env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    parts = line.split("=", 1)
                    k = parts[0].strip()
                    v = parts[1].strip().strip("'\"")
                    os.environ[k] = v

load_dotenv()
user = os.environ.get("CRM_DB_USER", "crm_app")
password = os.environ.get("CRM_DB_PASSWORD")
conn = psycopg2.connect(dbname="crm", user=user, password=password, host="127.0.0.1")
cur = conn.cursor()
cur.execute("""
    SELECT s.procurement_id, e.temporal_class, e.created_at 
    FROM crm_v3_learning_examples e 
    JOIN crm_v3_pre_research_snapshots s ON s.id = e.snapshot_id 
    WHERE s.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT' 
    LIMIT 5
""")
rows = cur.fetchall()
print(f"Materialized examples count: {len(rows)}")
for r in rows:
    print(r)
conn.close()
