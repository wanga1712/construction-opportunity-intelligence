import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

cur.execute("""
    SELECT id, procurement_id, queue_id, pipeline_generation, created_at
    FROM crm_v3_pre_research_snapshots 
    ORDER BY id DESC
    LIMIT 15
""")
for r in cur.fetchall():
    print(f"SnapID={r[0]}, PID={r[1]}, QID={r[2]}, Gen={r[3]}, Created={r[4]}")
