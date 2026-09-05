import psycopg2, psycopg2.extras

conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT count(*) FROM crm_v3_pre_research_snapshots")
    print("DIRECT PSYCOPG2 COUNT:", cur.fetchone())

from src.services.db_bootstrap import connect_databases
_, _, crm_db, _ = connect_databases()
print("CRM_DB CLASS:", type(crm_db).__name__)
try:
    rows = crm_db.execute_query("SELECT count(*) FROM crm_v3_pre_research_snapshots")
    print("CRM_DB EXECUTE_QUERY COUNT:", rows)
except Exception as e:
    print("CRM_DB EXECUTE_QUERY ERROR:", e)
