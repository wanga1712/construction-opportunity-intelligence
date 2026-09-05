import psycopg2, psycopg2.extras
from src.services.db_bootstrap import connect_databases

conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
with conn.cursor() as cur:
    cur.execute("SHOW search_path")
    print("DIRECT SEARCH PATH:", cur.fetchone())
    cur.execute("SELECT current_database(), current_user")
    print("DIRECT DB/USER:", cur.fetchone())

_, _, crm_db, _ = connect_databases()
rows1 = crm_db.execute_query("SHOW search_path")
print("CRM_DB SEARCH PATH:", rows1)
rows2 = crm_db.execute_query("SELECT current_database(), current_user")
print("CRM_DB DB/USER:", rows2)
