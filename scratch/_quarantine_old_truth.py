import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

quarantine_truth_ids = []

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT id, procurement_id, non_useful_documents_json, unknown_documents_json
        FROM crm_v3_exhaustive_truth
        WHERE producer_version = 'v3_real_truth'
    """)
    truths = cur.fetchall()

    for t in truths:
        pid = t["procurement_id"]
        non_useful = t["non_useful_documents_json"]
        if isinstance(non_useful, str):
            non_useful = json.loads(non_useful)

        if not non_useful:
            continue

        non_useful_ids = [d.get("source_document_id") for d in non_useful if d.get("source_document_id")]

        if not non_useful_ids:
            continue

        with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as d_cur:
            d_cur.execute("""
                SELECT f.id as source_document_id, f.download_status, r.status as parse_status
                FROM document_files f
                LEFT JOIN document_processing_results r ON f.id = r.file_id
                WHERE f.id IN %s
            """, (tuple(non_useful_ids),))
            rows = d_cur.fetchall()

        for r in rows:
            dl_st = str(r.get("download_status") or "").upper()
            pr_st = str(r.get("parse_status") or "").upper() if r.get("parse_status") else None
            if dl_st != "COMPLETED" or pr_st != "COMPLETED":
                quarantine_truth_ids.append(t["id"])
                break

print("AFFECTED TRUTHS TO QUARANTINE:", len(quarantine_truth_ids))

affected_evals = 0
affected_examples = 0

if quarantine_truth_ids:
    with crm_conn.cursor() as cur:
        cur.execute("""
            UPDATE crm_v3_exhaustive_truth
            SET producer_version = 'v3_quarantine_invalid_label_' || id::text
            WHERE id IN %s
        """, (tuple(quarantine_truth_ids),))

        cur.execute("""
            UPDATE crm_v3_shadow_evaluations
            SET producer_version = 'v3_quarantine_invalid_label_' || id::text
            WHERE truth_id IN %s
            RETURNING id
        """, (tuple(quarantine_truth_ids),))
        affected_evals = len(cur.fetchall())

        cur.execute("""
            UPDATE crm_v3_learning_examples
            SET producer_version = 'v3_quarantine_invalid_label_' || id::text
            WHERE truth_id IN %s
            RETURNING id
        """, (tuple(quarantine_truth_ids),))
        affected_examples = len(cur.fetchall())
    crm_conn.commit()

print(json.dumps({
    "affected_truths": len(quarantine_truth_ids),
    "affected_evaluations": affected_evals,
    "affected_learning_examples": affected_examples
}, indent=2))

crm_conn.close()
doc_conn.close()
