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
user = os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker")
password = os.environ.get("S13_DOCUMENT_DB_PASSWORD")
conn = psycopg2.connect(dbname="document_intelligence", user=user, password=password, host="127.0.0.1")
cur = conn.cursor()
cur.execute("""
    SELECT procurement_id, download_status FROM document_files
    WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
""")
rows = cur.fetchall()
print(f"Downloaded files: {len(rows)}")
for r in rows:
    print(r)
conn.close()
