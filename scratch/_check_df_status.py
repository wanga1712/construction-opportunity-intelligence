import psycopg2, psycopg2.extras, json

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT DISTINCT download_status FROM document_files")
    statuses = [r["download_status"] for r in cur.fetchall()]

    cur.execute("SELECT download_status, downloaded_at, created_at FROM document_files WHERE procurement_id = 150194")
    sample_df = cur.fetchall()

print("DISTINCT DOWNLOAD STATUSES:", json.dumps(statuses, indent=2))
print("SAMPLE DF FOR 150194:", json.dumps(sample_df, indent=2, default=str))
