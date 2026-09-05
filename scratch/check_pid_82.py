import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

cur.execute("SELECT id, procurement_id, pipeline_generation, research_generation_hash, producer_version FROM crm_v3_pre_research_snapshots WHERE procurement_id = 82")
rows = cur.fetchall()
print(f"Snapshots for PID 82 (total {len(rows)}):")
for r in rows:
    print(f"  ID={r[0]}, Gen={r[1]}, Hash={r[2]}, Ver={r[3]}")
conn.close()
