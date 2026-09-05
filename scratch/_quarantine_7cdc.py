import psycopg2

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

tables = [
    "crm_v3_pre_research_snapshots",
    "crm_v3_shadow_predictions",
    "crm_v3_exhaustive_truth",
    "crm_v3_shadow_evaluations",
    "crm_v3_learning_examples"
]

with crm_conn.cursor() as cur:
    for tbl in tables:
        cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS producer_version VARCHAR(64) DEFAULT 'v2_corrected';")
        cur.execute(f"UPDATE {tbl} SET producer_version = 'v1_invalid_7cdc' WHERE producer_version IS NULL OR producer_version = 'v1' OR producer_version = 'v2_corrected';")
crm_conn.commit()
crm_conn.close()
print("7CDC LEARNING DATA QUARANTINED SUCCESSFULLY")
