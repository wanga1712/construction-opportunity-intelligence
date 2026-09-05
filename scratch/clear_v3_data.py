import os
import psycopg2

CRM_DB_URL = "host=127.0.0.1 port=5432 dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX"
DOC_DB_URL = "host=127.0.0.1 port=5432 dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT"

GEN = "S13_V3_EXHAUSTIVE_CONTEXT"

def clear_doc_tables():
    conn = psycopg2.connect(DOC_DB_URL)
    cur = conn.cursor()
    
    # Get all file local_paths to delete them
    cur.execute("SELECT local_path FROM document_files WHERE pipeline_generation = %s", (GEN,))
    files = [r[0] for r in cur.fetchall() if r[0]]
    print(f"Found {len(files)} files to delete physically")
    deleted_files_count = 0
    for fpath in files:
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                deleted_files_count += 1
            except Exception as e:
                print(f"Error deleting file {fpath}: {e}")
    print(f"Successfully deleted {deleted_files_count} physical files")
    
    deleted_info = {}
    
    cur.execute("DELETE FROM document_match_details WHERE pipeline_generation = %s", (GEN,))
    deleted_info["document_match_details"] = cur.rowcount
    
    cur.execute("DELETE FROM document_matches WHERE pipeline_generation = %s", (GEN,))
    deleted_info["document_matches"] = cur.rowcount
    
    cur.execute("DELETE FROM document_processing_results WHERE pipeline_generation = %s", (GEN,))
    deleted_info["document_processing_results"] = cur.rowcount
    
    cur.execute("DELETE FROM document_files WHERE pipeline_generation = %s", (GEN,))
    deleted_info["document_files"] = cur.rowcount
    
    cur.execute("DELETE FROM document_processing_queue WHERE pipeline_generation = %s", (GEN,))
    deleted_info["document_processing_queue"] = cur.rowcount
    
    conn.commit()
    cur.close()
    conn.close()
    return deleted_info

def clear_crm_tables():
    conn = psycopg2.connect(CRM_DB_URL)
    cur = conn.cursor()
    
    deleted_info = {}
    
    # 1. crm_v3_learning_examples
    cur.execute("""
        DELETE FROM crm_v3_learning_examples 
        WHERE snapshot_id IN (
            SELECT id FROM crm_v3_pre_research_snapshots WHERE pipeline_generation = %s
        )
    """, (GEN,))
    deleted_info["crm_v3_learning_examples"] = cur.rowcount
    
    # 2. crm_v3_shadow_evaluations
    cur.execute("""
        DELETE FROM crm_v3_shadow_evaluations 
        WHERE prediction_id IN (
            SELECT id FROM crm_v3_shadow_predictions WHERE snapshot_id IN (
                SELECT id FROM crm_v3_pre_research_snapshots WHERE pipeline_generation = %s
            )
        )
    """, (GEN,))
    deleted_info["crm_v3_shadow_evaluations"] = cur.rowcount
    
    # 3. crm_v3_exhaustive_truth
    cur.execute("DELETE FROM crm_v3_exhaustive_truth WHERE pipeline_generation = %s", (GEN,))
    deleted_info["crm_v3_exhaustive_truth"] = cur.rowcount
    
    # 4. crm_v3_product_findings
    cur.execute("""
        DELETE FROM crm_v3_product_findings 
        WHERE research_generation_hash IN (
            SELECT DISTINCT research_generation_hash FROM crm_v3_pre_research_snapshots WHERE pipeline_generation = %s
        )
    """, (GEN,))
    deleted_info["crm_v3_product_findings"] = cur.rowcount
    
    # 5. crm_v3_raw_source_evidence
    cur.execute("DELETE FROM crm_v3_raw_source_evidence WHERE pipeline_generation = %s", (GEN,))
    deleted_info["crm_v3_raw_source_evidence"] = cur.rowcount
    
    # 6. crm_v3_shadow_predictions
    cur.execute("""
        DELETE FROM crm_v3_shadow_predictions 
        WHERE snapshot_id IN (
            SELECT id FROM crm_v3_pre_research_snapshots WHERE pipeline_generation = %s
        )
    """, (GEN,))
    deleted_info["crm_v3_shadow_predictions"] = cur.rowcount
    
    # 7. crm_v3_pre_research_snapshots
    cur.execute("DELETE FROM crm_v3_pre_research_snapshots WHERE pipeline_generation = %s", (GEN,))
    deleted_info["crm_v3_pre_research_snapshots"] = cur.rowcount
    
    conn.commit()
    cur.close()
    conn.close()
    return deleted_info

def main():
    print("Clearing document_intelligence V3 data...")
    doc_del = clear_doc_tables()
    print("Deleted doc rows:", doc_del)
    
    print("Clearing crm V3 data...")
    crm_del = clear_crm_tables()
    print("Deleted crm rows:", crm_del)

if __name__ == "__main__":
    main()
