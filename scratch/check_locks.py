import psycopg2
conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()

cur.execute("""
    SELECT pid, age(query_start, clock_timestamp()), usename, query, state 
    FROM pg_stat_activity 
    WHERE query != '<insufficient privilege>' AND query NOT LIKE '%pg_stat_activity%' AND state != 'idle'
""")
print("=== Active Queries on crm DB ===")
for r in cur.fetchall():
    print(f"PID={r[0]}, Age={r[1]}, User={r[2]}, Query={r[3]}, State={r[4]}")

conn.close()

conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='document_intelligence',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor()
cur.execute("""
    SELECT pid, age(query_start, clock_timestamp()), usename, query, state 
    FROM pg_stat_activity 
    WHERE query != '<insufficient privilege>' AND query NOT LIKE '%pg_stat_activity%' AND state != 'idle'
""")
print("=== Active Queries on document_intelligence DB ===")
for r in cur.fetchall():
    print(f"PID={r[0]}, Age={r[1]}, User={r[2]}, Query={r[3]}, State={r[4]}")
conn.close()
