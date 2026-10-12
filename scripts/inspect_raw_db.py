import json
import psycopg2
from psycopg2.extras import RealDictCursor

conn_crm = psycopg2.connect("dbname=crm user=postgres")
with conn_crm.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute("""
        SELECT procurement_id, validated_model_result, raw_model_text
        FROM crm_v3_model_inference_runs
        WHERE procurement_id IN (164721, 93275, 65654, 163638) AND prompt_version = 'v3_second_pass_evidence_7b_v2'
        ORDER BY procurement_id
    """)
    rows = cur.fetchall()

for r in rows:
    print("=" * 60)
    print(f"PROCUREMENT {r['procurement_id']}")
    print("RAW TEXT:")
    print(r["raw_model_text"])
