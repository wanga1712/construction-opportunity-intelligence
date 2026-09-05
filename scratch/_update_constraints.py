import psycopg2

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

ddls = [
    "ALTER TABLE crm_v3_pre_research_snapshots DROP CONSTRAINT IF EXISTS uq_snapshot_proc_gen;",
    "ALTER TABLE crm_v3_pre_research_snapshots ADD CONSTRAINT uq_snapshot_proc_gen_ver UNIQUE (procurement_id, research_generation_hash, producer_version);",
    "ALTER TABLE crm_v3_exhaustive_truth DROP CONSTRAINT IF EXISTS uq_truth_proc_gen;",
    "ALTER TABLE crm_v3_exhaustive_truth ADD CONSTRAINT uq_truth_proc_gen_ver UNIQUE (procurement_id, research_generation_hash, producer_version);"
]

with crm_conn.cursor() as cur:
    for d in ddls:
        cur.execute(d)
crm_conn.commit()
crm_conn.close()
print("UNIQUE CONSTRAINTS UPDATED WITH PRODUCER_VERSION")
