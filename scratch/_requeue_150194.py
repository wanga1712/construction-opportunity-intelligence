import psycopg2

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

with doc_conn.cursor() as cur:
    cur.execute("UPDATE document_processing_queue SET status = 'PENDING' WHERE procurement_id = 150194;")
doc_conn.commit()
doc_conn.close()
print("PROCUREMENT 150194 RESET TO PENDING FOR POSITIVE PROOF EXECUTION")
