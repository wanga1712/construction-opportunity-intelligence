import psycopg2
import json

def get_crm_db():
    import os
    user = os.environ.get("CRM_DB_USER", "crm_app")
    password = os.environ.get("CRM_DB_PASSWORD")
    host = os.environ.get("CRM_DB_HOST", "127.0.0.1")
    port = os.environ.get("CRM_DB_PORT", "5432")
    return psycopg2.connect(dbname="crm", user=user, password=password, host=host, port=port)

def get_doc_db():
    import os
    user = os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker")
    password = os.environ.get("S13_DOCUMENT_DB_PASSWORD")
    host = os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1")
    port = os.environ.get("S13_DOCUMENT_DB_PORT", "5432")
    return psycopg2.connect(dbname="document_intelligence", user=user, password=password, host=host, port=port)

def main():
    doc_conn = get_doc_db()
    crm_conn = get_crm_db()
    try:
        # Fetch S13_V4_EXHAUSTIVE_CONTEXT queue rows
        doc_cur = doc_conn.cursor()
        doc_cur.execute("""
            SELECT id, procurement_id, status, category_context, research_generation_hash
            FROM document_processing_queue
            WHERE pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
        """)
        queue_rows = doc_cur.fetchall()
        print(f"Total S13_V4_EXHAUSTIVE_CONTEXT queue rows: {len(queue_rows)}")
        
        for q_id, pid, status, cat_ctx, gen_hash in queue_rows:
            # Check if downloaded files/content exist in Document DB
            doc_cur.execute("""
                SELECT COUNT(1) FROM document_files
                WHERE procurement_id = %s AND download_status = 'COMPLETED'
            """, (pid,))
            downloaded_count = doc_cur.fetchone()[0]
            
            content_exists = downloaded_count > 0
            
            if not content_exists:
                # Class A: No download/content exists -> Safely move to PRE_RESEARCH_WAITING
                if status != "PRE_RESEARCH_WAITING":
                    doc_cur.execute("""
                        UPDATE document_processing_queue
                        SET status = 'PRE_RESEARCH_WAITING'
                        WHERE id = %s
                    """, (q_id,))
                    print(f"Procurement {pid} (row {q_id}): No content. Moved to PRE_RESEARCH_WAITING.")
            else:
                # Content already exists. Check if valid blind prediction was created BEFORE content.
                # 1. Get first downloaded_at timestamp
                doc_cur.execute("""
                    SELECT MIN(downloaded_at) FROM document_files
                    WHERE procurement_id = %s AND download_status = 'COMPLETED'
                """, (pid,))
                first_download_at = doc_cur.fetchone()[0]
                
                # 2. Get first parsed content completed_at timestamp
                doc_cur.execute("""
                    SELECT MIN(r.completed_at) FROM document_files f
                    JOIN document_processing_results r ON f.id = r.file_id
                    WHERE f.procurement_id = %s AND r.status = 'COMPLETED'
                """, (pid,))
                first_parsed_at = doc_cur.fetchone()[0]
                
                content_avail_at = first_parsed_at or first_download_at
                
                # 3. Check for valid blind prediction
                crm_cur = crm_conn.cursor()
                crm_cur.execute("""
                    SELECT MIN(p.created_at) FROM crm_v3_shadow_predictions p
                    JOIN crm_v3_pre_research_snapshots s ON p.snapshot_id = s.id
                    WHERE s.procurement_id = %s AND s.research_generation_hash = %s AND s.pipeline_generation = 'S13_V4_EXHAUSTIVE_CONTEXT'
                """, (pid, gen_hash))
                prediction_at = crm_cur.fetchone()[0]
                
                ctx = cat_ctx
                if isinstance(ctx, str):
                    ctx = json.loads(ctx)
                ctx = dict(ctx or {})
                
                if prediction_at and content_avail_at and prediction_at < content_avail_at:
                    # Class B: Valid prediction created before content -> ONLINE_CLEAN continues
                    ctx["learning_sample_mode"] = "ONLINE_CLEAN"
                    ctx["blind_prediction_status"] = "SUCCESS"
                    doc_cur.execute("""
                        UPDATE document_processing_queue
                        SET category_context = %s
                        WHERE id = %s
                    """, (json.dumps(ctx), q_id))
                    print(f"Procurement {pid} (row {q_id}): Valid prediction before content. Mode set to ONLINE_CLEAN.")
                else:
                    # Class C: Content exists but no clean blind prediction before content -> BACKFILL_FACT_ONLY
                    ctx["learning_sample_mode"] = "BACKFILL_FACT_ONLY"
                    ctx["blind_prediction_status"] = "FAILED" if prediction_at else "UNAVAILABLE"
                    # Release status must remain PENDING
                    doc_cur.execute("""
                        UPDATE document_processing_queue
                        SET status = 'PENDING',
                            category_context = %s
                        WHERE id = %s
                    """, (json.dumps(ctx), q_id))
                    print(f"Procurement {pid} (row {q_id}): Content exists but no blind prediction before it. Mode set to BACKFILL_FACT_ONLY.")
        
        doc_conn.commit()
        print("Classification migration completed successfully!")
    finally:
        doc_conn.close()
        crm_conn.close()

if __name__ == "__main__":
    main()
