import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

cur.execute("""
    SELECT table_name, table_type 
    FROM information_schema.tables 
    WHERE table_name = 'crm_v3_shadow_predictions'
""")
print(cur.fetchone())

# If it is a view, print its definition
cur.execute("""
    SELECT view_definition 
    FROM information_schema.views 
    WHERE table_name = 'crm_v3_shadow_predictions'
""")
r = cur.fetchone()
if r:
    print("View definition:")
    print(r[0])
conn.close()
