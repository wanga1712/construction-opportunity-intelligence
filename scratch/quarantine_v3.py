import os
import sys
import json
import psycopg2
import psycopg2.extras

CRM_DB_URL = "host=127.0.0.1 port=5432 dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX"
DOC_DB_URL = "host=127.0.0.1 port=5432 dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT"

GEN = "S13_V3_EXHAUSTIVE_CONTEXT"

def get_columns(cur, table):
    cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
    return [r[0] for r in cur.fetchall()]

def dump_table(cur, table, pids, limit=5):
    cols = get_columns(cur, table)
    if not cols:
        return {"error": "table not found", "count": 0, "sample": []}
    
    count = 0
    sample = []
    
    if "pipeline_generation" in cols:
        cur.execute(f"SELECT count(*) FROM {table} WHERE pipeline_generation = %s", (GEN,))
        count = cur.fetchone()[0]
        cur.execute(f"SELECT * FROM {table} WHERE pipeline_generation = %s LIMIT %s", (GEN, limit))
        sample = cur.fetchall()
    elif "procurement_id" in cols:
        if pids:
            cur.execute(f"SELECT count(*) FROM {table} WHERE procurement_id = ANY(%s)", (pids,))
            count = cur.fetchone()[0]
            cur.execute(f"SELECT * FROM {table} WHERE procurement_id = ANY(%s) LIMIT %s", (pids, limit))
            sample = cur.fetchall()
    elif table == "crm_v3_shadow_evaluations":
        # Join with predictions, then snapshots
        if pids:
            cur.execute(f"""
                SELECT count(*) FROM crm_v3_shadow_evaluations e
                JOIN crm_v3_shadow_predictions p ON e.prediction_id = p.id
                WHERE p.procurement_id = ANY(%s)
            """, (pids,))
            count = cur.fetchone()[0]
            cur.execute(f"""
                SELECT e.* FROM crm_v3_shadow_evaluations e
                JOIN crm_v3_shadow_predictions p ON e.prediction_id = p.id
                WHERE p.procurement_id = ANY(%s) LIMIT %s
            """, (pids, limit))
            sample = cur.fetchall()
            
    # convert sample to dict using description
    sample_dicts = []
    if sample:
        desc = cur.description
        headers = [d[0] for d in desc]
        for row in sample:
            d = {}
            for h, v in zip(headers, row):
                if isinstance(v, bytes):
                    d[h] = v.hex()
                elif hasattr(v, 'isoformat'):
                    d[h] = v.isoformat()
                else:
                    d[h] = v
            sample_dicts.append(d)
            
    return {"count": count, "sample": sample_dicts}

def main():
    # Let's get the list of procurement_ids for GEN from pre_research_snapshots
    conn_crm = psycopg2.connect(CRM_DB_URL)
    cur_crm = conn_crm.cursor()
    cur_crm.execute("SELECT DISTINCT procurement_id FROM crm_v3_pre_research_snapshots WHERE pipeline_generation = %s", (GEN,))
    crm_pids = [r[0] for r in cur_crm.fetchall()]
    print(f"Found {len(crm_pids)} procurement_ids in crm_v3_pre_research_snapshots for {GEN}")
    
    dump_data = {}
    
    # 1. Dump crm tables
    crm_tables = [
        "crm_v3_pre_research_snapshots",
        "crm_v3_shadow_predictions",
        "crm_v3_raw_source_evidence",
        "crm_v3_product_findings",
        "crm_v3_exhaustive_truth",
        "crm_v3_shadow_evaluations",
        "crm_v3_learning_examples"
    ]
    
    print("Dumping crm...")
    for table in crm_tables:
        dump_data[table] = dump_table(cur_crm, table, crm_pids)
        print(f"  {table}: {dump_data[table]['count']} rows")
        
    cur_crm.close()
    conn_crm.close()
    
    # 2. Dump doc tables
    conn_doc = psycopg2.connect(DOC_DB_URL)
    cur_doc = conn_doc.cursor()
    
    doc_tables = [
        "document_processing_queue",
        "document_files",
        "document_processing_results",
        "document_matches",
        "document_match_details"
    ]
    
    print("Dumping document_intelligence...")
    for table in doc_tables:
        dump_data[table] = dump_table(cur_doc, table, crm_pids)
        print(f"  {table}: {dump_data[table]['count']} rows")
        
    cur_doc.close()
    conn_doc.close()
    
    # Save to file
    with open("/tmp/failed_v3_quarantine.json", "w", encoding="utf-8") as f:
        json.dump(dump_data, f, ensure_ascii=False, indent=2)
    print("Quarantine dump written to /tmp/failed_v3_quarantine.json")

if __name__ == "__main__":
    main()
