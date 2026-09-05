import psycopg2, psycopg2.extras, json

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

# Find truths where truth.created_at < queue completed_at / last_doc_at or prediction created after truth
quarantined_truth_ids = []

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT t.id as truth_id, t.procurement_id, t.created_at as truth_at,
               p.id as pred_id, p.created_at as pred_at
        FROM crm_v3_exhaustive_truth t
        LEFT JOIN crm_v3_shadow_predictions p 
          ON t.procurement_id = p.procurement_id 
         AND t.research_generation_hash = p.research_generation_hash
        WHERE t.producer_version = 'v3_real_truth'
    """)
    truths = cur.fetchall()

    for r in truths:
        pid = r["procurement_id"]
        truth_at = r["truth_at"]
        pred_at = r["pred_at"]
        
        # Get max completed_at from queue or max downloaded_at from document_files
        with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as d_cur:
            d_cur.execute("""
                SELECT completed_at FROM document_processing_queue
                WHERE procurement_id = %s AND pipeline_generation = 'S13_V2'
            """, (pid,))
            q_row = d_cur.fetchone()
            q_at = q_row["completed_at"] if q_row else None

            d_cur.execute("""
                SELECT MAX(downloaded_at) as max_doc_at FROM document_files
                WHERE procurement_id = %s
            """, (pid,))
            df_row = d_cur.fetchone()
            doc_at = df_row["max_doc_at"] if df_row else None

        last_term_at = max(filter(None, [q_at, doc_at]), default=None)

        is_premature = False
        if last_term_at and truth_at < last_term_at:
            is_premature = True
        if pred_at and pred_at >= truth_at:
            # Prediction was created AFTER truth was already generated (violates blind prediction before truth order)
            is_premature = True

        if is_premature:
            quarantined_truth_ids.append(r["truth_id"])

print("FOUND PREMATURE TRUTH IDS:", json.dumps(quarantined_truth_ids, indent=2))

if quarantined_truth_ids:
    with crm_conn.cursor() as cur:
        cur.execute("""
            UPDATE crm_v3_exhaustive_truth
            SET producer_version = 'v3_premature_quarantine_' || id::text
            WHERE id IN %s
        """, (tuple(quarantined_truth_ids),))

        cur.execute("""
            UPDATE crm_v3_shadow_evaluations
            SET producer_version = 'v3_premature_quarantine_' || id::text
            WHERE truth_id IN %s
        """, (tuple(quarantined_truth_ids),))

        cur.execute("""
            UPDATE crm_v3_learning_examples
            SET producer_version = 'v3_premature_quarantine_' || id::text
            WHERE truth_id IN %s
        """, (tuple(quarantined_truth_ids),))
    crm_conn.commit()
    print("QUARANTINED PREMATURE TRUTHS SUCCESSFULLY")

crm_conn.close()
doc_conn.close()
