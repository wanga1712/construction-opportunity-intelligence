import psycopg2, psycopg2.extras, json, subprocess, hashlib, os

doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")
crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id, procurement_id, queue_lane, priority_score, status, research_generation_hash, created_at FROM document_processing_queue WHERE pipeline_generation = %s AND status = 'COMPLETED' ORDER BY id DESC LIMIT 10", ("S13_V2",))
    comp_q = cur.fetchall()

p_ids = [r["procurement_id"] for r in comp_q if r["procurement_id"]]

crm_info, ev_info, runs_info, trace_info = {}, {}, {}, {}

if p_ids:
    with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT p.id, p.crm_stage FROM crm_procurements p WHERE p.id IN %s", (tuple(p_ids),))
        for r in cur.fetchall(): crm_info[r["id"]] = r

        cur.execute("SELECT procurement_id, COUNT(1) as cnt FROM crm_v3_raw_source_evidence WHERE procurement_id IN %s GROUP BY procurement_id", (tuple(p_ids),))
        for r in cur.fetchall(): ev_info[r["procurement_id"]] = r["cnt"]

        cur.execute("SELECT procurement_id, prompt_version, id, created_at FROM crm_v3_model_inference_runs WHERE procurement_id IN %s", (tuple(p_ids),))
        for r in cur.fetchall():
            pid = r["procurement_id"]
            if pid not in runs_info: runs_info[pid] = {}
            role = "HUNTER" if "hunter" in r["prompt_version"] else "AUDITOR"
            runs_info[pid][role] = {"id": r["id"], "at": str(r["created_at"])}

        cur.execute("SELECT * FROM crm_v3_autonomous_analysis_traces WHERE procurement_id IN %s", (tuple(p_ids),))
        for r in cur.fetchall(): trace_info[r["procurement_id"]] = r

completed_rows = []
for q in comp_q:
    pid = q["procurement_id"]
    info = crm_info.get(pid, {})
    tr = trace_info.get(pid, {})
    runs = runs_info.get(pid, {})
    completed_rows.append({
        "PROCUREMENT_ID": pid,
        "QUEUE_ID": q["id"],
        "QUEUE_LANE": q["queue_lane"],
        "PRIORITY_SCORE": q["priority_score"],
        "RESEARCH_GENERATION_HASH": q["research_generation_hash"],
        "COMPLETED_AT": str(q["created_at"]),
        "RAW_EVIDENCE_COUNT": ev_info.get(pid, 0),
        "HUNTER_RUN": runs.get("HUNTER"),
        "AUDITOR_RUN": runs.get("AUDITOR"),
        "CONSENSUS_STATE": tr.get("consensus_state"),
        "TRACE_ID": tr.get("id"),
        "TRACE_LAST_ERROR": tr.get("last_error")
    })

print(json.dumps({
    "completed_rows": completed_rows
}, indent=2))
