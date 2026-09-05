import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT DISTINCT procurement_id, pipeline_generation, research_generation_hash, source_document_id
        FROM crm_v3_raw_source_evidence
        LIMIT 20
    """)
    ev_all = cur.fetchall()

print(json.dumps(ev_all, indent=2))
