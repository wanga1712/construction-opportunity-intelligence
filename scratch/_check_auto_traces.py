import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT hunter_run_id, auditor_run_id, consensus_state, created_at, last_error
        FROM crm_v3_autonomous_analysis_traces
        ORDER BY id DESC LIMIT 5
    """)
    traces = cur.fetchall()

print(json.dumps(traces, indent=2, default=str))
