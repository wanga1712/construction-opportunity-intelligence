import psycopg2, psycopg2.extras, json, hashlib

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")
crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

def compute_sha256(val):
    if isinstance(val, (dict, list)):
        s = json.dumps(val, sort_keys=True, ensure_ascii=False)
    else:
        s = str(val or "")
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, procurement_id, research_generation_hash FROM document_processing_queue WHERE pipeline_generation = 'S13_V2' LIMIT 5")
    q_items = cur.fetchall()

reasons = []
for item in q_items:
    pid = item["procurement_id"]
    gen_hash = item["research_generation_hash"] or compute_sha256(pid)
    
    with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c_cur:
        c_cur.execute("""
            SELECT id FROM crm_v3_pre_research_snapshots
            WHERE procurement_id = %s AND research_generation_hash = %s AND producer_version = 'v2_corrected'
        """, (pid, gen_hash))
        snap = c_cur.fetchone()

        c_cur.execute("SELECT id FROM crm_procurements WHERE id = %s", (pid,))
        p_fact = c_cur.fetchone()

        reasons.append({
            "pid": pid,
            "gen_hash": gen_hash,
            "snap_exists": bool(snap),
            "p_fact_exists": bool(p_fact)
        })

print(json.dumps(reasons, indent=2))
