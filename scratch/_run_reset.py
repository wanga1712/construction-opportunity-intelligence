import psycopg2
import psycopg2.extras
import json
import os
import shutil

# Connect to document_intelligence DB
doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

# Connect to crm DB
crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

def count_table(conn, table_name):
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {table_name}")
            return cur.fetchone()[0]
    except Exception:
        conn.rollback()
        return -1

# 1. Count BEFORE reset
before_counts = {
    "QUEUE": count_table(doc_conn, "document_processing_queue"),
    "DOCUMENT_FILES": count_table(doc_conn, "document_files"),
    "PROCESSING_RESULTS": count_table(doc_conn, "document_processing_results"),
    "DOCUMENT_MATCHES": count_table(doc_conn, "document_matches"),
    "DOCUMENT_MATCH_DETAILS": count_table(doc_conn, "document_match_details"),

    "SNAPSHOTS": count_table(crm_conn, "crm_v3_pre_research_snapshots"),
    "SHADOW_PREDICTIONS": count_table(crm_conn, "crm_v3_shadow_predictions"),
    "RAW_EVIDENCE": count_table(crm_conn, "crm_v3_raw_source_evidence"),
    "PRODUCT_FINDINGS": count_table(crm_conn, "crm_v3_product_findings"),
    "TRUTHS": count_table(crm_conn, "crm_v3_exhaustive_truth"),
    "EVALUATIONS": count_table(crm_conn, "crm_v3_shadow_evaluations"),
    "LEARNING_EXAMPLES": count_table(crm_conn, "crm_v3_learning_examples"),
}

preserved_counts = {
    "SOURCE_PROCUREMENTS": count_table(crm_conn, "crm_procurements"),
    "SOURCE_DOCUMENT_LINKS": count_table(crm_conn, "links_documentation_fz44") if count_table(crm_conn, "links_documentation_fz44") >= 0 else 0,
    "HUMAN_ANNOTATIONS": count_table(crm_conn, "expert_annotations") if count_table(crm_conn, "expert_annotations") >= 0 else 0,
    "CATEGORY_REGISTRY": count_table(crm_conn, "crm_product_categories"),
}

# 2. Reset active tables in document_intelligence DB
doc_tables_to_truncate = [
    "document_match_details",
    "document_matches",
    "document_processing_results",
    "document_files",
    "document_processing_queue",
]

with doc_conn.cursor() as cur:
    for t in doc_tables_to_truncate:
        try:
            cur.execute(f"TRUNCATE TABLE {t} CASCADE")
        except Exception as e:
            doc_conn.rollback()
            print(f"Error truncating {t}: {e}")
            break
    else:
        doc_conn.commit()

# 3. Reset active tables in crm DB
crm_tables_to_truncate = [
    "crm_v3_learning_examples",
    "crm_v3_shadow_evaluations",
    "crm_v3_exhaustive_truth",
    "crm_v3_product_findings",
    "crm_v3_raw_source_evidence",
    "crm_v3_shadow_predictions",
    "crm_v3_pre_research_snapshots",
]

with crm_conn.cursor() as cur:
    for t in crm_tables_to_truncate:
        try:
            cur.execute(f"TRUNCATE TABLE {t} CASCADE")
        except Exception as e:
            crm_conn.rollback()
            print(f"Error truncating {t}: {e}")
            break
    else:
        crm_conn.commit()

# 4. Clean physical active directory
active_dir = "/opt/tender_documents_research"
if os.path.exists(active_dir):
    for item in os.listdir(active_dir):
        item_path = os.path.join(active_dir, item)
        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
        except Exception as e:
            print(f"Error cleaning {item_path}: {e}")

# 5. Count AFTER reset
after_counts = {
    "QUEUE": count_table(doc_conn, "document_processing_queue"),
    "DOCUMENT_FILES": count_table(doc_conn, "document_files"),
    "PROCESSING_RESULTS": count_table(doc_conn, "document_processing_results"),
    "DOCUMENT_MATCHES": count_table(doc_conn, "document_matches"),
    "DOCUMENT_MATCH_DETAILS": count_table(doc_conn, "document_match_details"),

    "SNAPSHOTS": count_table(crm_conn, "crm_v3_pre_research_snapshots"),
    "SHADOW_PREDICTIONS": count_table(crm_conn, "crm_v3_shadow_predictions"),
    "RAW_EVIDENCE": count_table(crm_conn, "crm_v3_raw_source_evidence"),
    "PRODUCT_FINDINGS": count_table(crm_conn, "crm_v3_product_findings"),
    "TRUTHS": count_table(crm_conn, "crm_v3_exhaustive_truth"),
    "EVALUATIONS": count_table(crm_conn, "crm_v3_shadow_evaluations"),
    "LEARNING_EXAMPLES": count_table(crm_conn, "crm_v3_learning_examples"),
}

doc_conn.close()
crm_conn.close()

out = {
    "RESET_BEFORE": before_counts,
    "RESET_AFTER": after_counts,
    "PRESERVED": preserved_counts,
}

print("=== RESET COMPLETED ===")
print(json.dumps(out, indent=2))
