import psycopg2

conn = psycopg2.connect('host=127.0.0.1 port=5432 dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT')
cur = conn.cursor()
cur.execute("""
    SELECT trigger_name, event_manipulation, action_statement
    FROM information_schema.triggers
    WHERE event_object_table = 'document_files'
""")
print("Triggers on document_files:", cur.fetchall())

cur.execute("""
    SELECT trigger_name, event_manipulation, action_statement
    FROM information_schema.triggers
    WHERE event_object_table = 'document_processing_queue'
""")
print("Triggers on document_processing_queue:", cur.fetchall())

conn.close()
