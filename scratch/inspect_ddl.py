import psycopg2

conn = psycopg2.connect('host=127.0.0.1 port=5432 dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT')
cur = conn.cursor()

for table in ['document_processing_queue', 'document_processing_results', 'document_matches', 'document_match_details']:
    cur.execute("""
        SELECT column_name, column_default, data_type
        FROM information_schema.columns
        WHERE table_name = %s
    """, (table,))
    print(f"{table} columns and defaults:")
    for r in cur.fetchall():
        print(f"  {r[0]}: default={r[1]}, type={r[2]}")

conn.close()
