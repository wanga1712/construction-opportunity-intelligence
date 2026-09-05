import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'crm_v3_raw_source_evidence'")
    ev_cols = [r["column_name"] for r in cur.fetchall()]

    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'crm_v3_exhaustive_truth'")
    truth_cols = [r["column_name"] for r in cur.fetchall()]

    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'crm_v3_pre_research_snapshots'")
    snap_cols = [r["column_name"] for r in cur.fetchall()]

print("EV COLS:", json.dumps(ev_cols, indent=2))
print("TRUTH COLS:", json.dumps(truth_cols, indent=2))
print("SNAP COLS:", json.dumps(snap_cols, indent=2))
