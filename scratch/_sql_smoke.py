import psycopg2, psycopg2.extras, json

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")
crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

# Test 1: document_processing_queue query with alias q
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT q.id, q.procurement_id, q.queue_lane, q.priority_score, q.status
        FROM document_processing_queue q
        WHERE q.status IN ('COMPLETED', 'FAILED', 'NO_LINKS')
          AND q.pipeline_generation = %s
        ORDER BY 
          CASE q.queue_lane 
            WHEN 'crm_active_hot' THEN 1 
            WHEN 'open_active' THEN 2 
            WHEN 'awarded_recent' THEN 3 
            WHEN 'retry' THEN 4 
            WHEN 'historical_awarded' THEN 5 
            ELSE 6 
          END ASC,
          q.priority_score DESC,
          q.id DESC
        LIMIT 10
    """, ("S13_V2",))
    q_rows = cur.fetchall()

# Test 2: crm_v3_autonomous_analysis_traces query without queue_lane reference
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, consensus_state
        FROM crm_v3_autonomous_analysis_traces
        ORDER BY id DESC
        LIMIT 5
    """)
    tr_rows = cur.fetchall()

print(json.dumps({
    "q_rows_len": len(q_rows),
    "tr_rows_len": len(tr_rows),
    "status": "PASS"
}))
