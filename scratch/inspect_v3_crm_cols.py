import psycopg2

conn = psycopg2.connect('host=127.0.0.1 port=5432 dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX')
cur = conn.cursor()
tables = [
    'crm_v3_pre_research_snapshots',
    'crm_v3_shadow_predictions',
    'crm_v3_raw_source_evidence',
    'crm_v3_product_findings',
    'crm_v3_exhaustive_truth',
    'crm_v3_shadow_evaluations',
    'crm_v3_learning_examples'
]
for t in tables:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (t,))
    cols = [r[0] for r in cur.fetchall()]
    print(t, cols)
conn.close()
