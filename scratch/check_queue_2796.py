import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

cur.execute("""
    SELECT id, procurement_id, pipeline_generation, status, created_at 
    FROM document_processing_queue 
    WHERE id = 2796
""")
r = cur.fetchone()
if r:
    print(f"QID={r[0]}, PID={r[1]}, Gen={r[2]}, Status={r[3]}, Created={r[4]}")
else:
    print("Not found")
