import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

cur.execute("SELECT id, procurement_id, pipeline_generation, status FROM document_processing_queue WHERE procurement_id = 82")
rows = cur.fetchall()
print(f"Queue rows for PID 82 (total {len(rows)}):")
for r in rows:
    print(f"  ID={r[0]}, PID={r[1]}, Gen={r[2]}, Status={r[3]}")
conn.close()
