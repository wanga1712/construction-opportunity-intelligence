import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

print("=== Comparing snapshots and queue hashes ===")
cur.execute("SELECT id, procurement_id, research_generation_hash, producer_version FROM crm_v3_pre_research_snapshots LIMIT 5")
print("Snapshots:")
for r in cur.fetchall():
    print(f"  SnapID={r[0]}, PID={r[1]}, Hash={r[2]}, Ver={r[3]}")

# Also query the document intelligence queue items
doc_conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
d_cur=doc_conn.cursor()
d_cur.execute("""
    SELECT id, procurement_id, research_generation_hash, status 
    FROM document_processing_queue 
    WHERE pipeline_generation = 'S13_V3_EXHAUSTIVE_CONTEXT' AND status IN ('COMPLETED', 'FAILED')
    LIMIT 5
""")
print("Queue:")
for r in d_cur.fetchall():
    print(f"  QID={r[0]}, PID={r[1]}, Hash={r[2]}, Status={r[3]}")
