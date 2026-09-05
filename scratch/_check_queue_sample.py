import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

class DummyDB:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, query, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return [dict(r) for r in cur.fetchall()]

crm_db = DummyDB(crm_conn)
doc_db = DummyDB(doc_conn)

# Get 50 recent procurements from crm_procurements
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id FROM crm_procurements ORDER BY id DESC LIMIT 50")
    pids = [r["id"] for r in cur.fetchall()]

# Check queue statuses in document_processing_queue for these pids
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT procurement_id, status, research_generation_hash FROM document_processing_queue WHERE pipeline_generation = 'S13_V2' AND procurement_id IN %s", (tuple(pids),))
    q_rows = cur.fetchall()

print("RECENT 50 PIDS:", len(pids))
print("QUEUE ROWS FOUND:", len(q_rows))
print("SAMPLE QUEUE ROWS:", json.dumps(q_rows[:10], indent=2, default=str))

crm_conn.close()
doc_conn.close()
