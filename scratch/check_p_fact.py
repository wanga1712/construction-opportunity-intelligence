import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

cur.execute("SELECT id FROM crm_procurements ORDER BY id LIMIT 10")
print("Small crm_procurements IDs:")
for r in cur.fetchall():
    print(r[0])

cur.execute("SELECT id FROM crm_procurements ORDER BY id DESC LIMIT 10")
print("Large crm_procurements IDs:")
for r in cur.fetchall():
    print(r[0])
