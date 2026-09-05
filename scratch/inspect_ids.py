import psycopg2
conn = psycopg2.connect(host="127.0.0.1", port=5432, dbname="document_intelligence", user="crm_app", password="X17B3n5hbANQSRt6i7WIyy0lJudX")
cur = conn.cursor()
cur.execute("SELECT id, source_id, file_name FROM document_files WHERE id >= 1100 LIMIT 5")
for r in cur.fetchall():
    print(f"ID={r[0]}, SourceID={r[1]}, Name={r[2]}")
