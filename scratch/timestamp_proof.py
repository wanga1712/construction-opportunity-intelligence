import psycopg2
import psycopg2.extras

conn=psycopg2.connect(host='127.0.0.1',port=5432,dbname='crm',user='crm_app',password='X17B3n5hbANQSRt6i7WIyy0lJudX')
cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("""
    SELECT s.procurement_id, s.created_at as snap_at, t.created_at as truth_at
    FROM crm_v3_pre_research_snapshots s
    JOIN crm_v3_exhaustive_truth t ON s.procurement_id = t.procurement_id
    LIMIT 3
""")
rows = cur.fetchall()
print("=== End-to-End Timestamp Proof ===")
for r in rows:
    pid = r["procurement_id"]
    snap_at = r["snap_at"]
    truth_at = r["truth_at"]
    print(f"Procurement {pid}:")
    print(f"  1. Pre-research Snapshot created at: {snap_at}")
    print(f"  2. Exhaustive Truth created at:      {truth_at}")
    if snap_at < truth_at:
        print("  -> SUCCESS: SNAP_AT < TRUTH_AT (Strict temporal order verified!)")
    else:
        print("  -> ERROR: Invalid temporal order!")
conn.close()
