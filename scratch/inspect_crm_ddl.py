import psycopg2

conn = psycopg2.connect('host=127.0.0.1 port=5432 dbname=crm user=crm_app password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT')
cur = conn.cursor()

cur.execute("""
    SELECT column_name, column_default, data_type
    FROM information_schema.columns
    WHERE table_name = 'crm_v3_raw_source_evidence'
""")
print("crm_v3_raw_source_evidence columns:")
for r in cur.fetchall():
    print(f"  {r[0]}: default={r[1]}, type={r[2]}")

conn.close()
