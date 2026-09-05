import psycopg2, json
from src.services.commercial_routing_v3.research_ui_projection import load_research_ui_projection, PIPELINE_GENERATION

class DummyDB:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, query, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return [dict(r) for r in cur.fetchall()]

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
doc_conn = psycopg2.connect("dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT host=127.0.0.1 port=5432")

crm_db = DummyDB(crm_conn)
doc_db = DummyDB(doc_conn)

pid = 150194
projs = load_research_ui_projection([pid], crm_db, doc_db)
p = projs[pid]

# Fetch DB truth numbers directly
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("""
        SELECT documents_total, useful_documents_json, evidence_count
        FROM crm_v3_exhaustive_truth
        WHERE procurement_id = %s AND producer_version = 'v3_real_truth'
    """, (pid,))
    t_row = cur.fetchone()

    cur.execute("""
        SELECT source_document_id, suggested_category_code
        FROM crm_v3_raw_source_evidence
        WHERE procurement_id = %s AND pipeline_generation = %s
    """, (pid, PIPELINE_GENERATION))
    e_rows = cur.fetchall()

useful_docs = t_row["useful_documents_json"] if t_row else []
if isinstance(useful_docs, str):
    useful_docs = json.loads(useful_docs)

db_useful_doc_ids = sorted(list({d["source_document_id"] for d in useful_docs if "source_document_id" in d}))
db_cat_codes = sorted(list({r["suggested_category_code"] for r in e_rows if r["suggested_category_code"]}))

result = {
    "PROCUREMENT_ID": pid,
    "RESEARCH_GENERATION_HASH": p.research_generation_hash,
    "UI_DOCUMENTS_TOTAL": p.documents_total,
    "DB_DOCUMENTS_TOTAL": t_row["documents_total"] if t_row else p.documents_total,
    "UI_DOCUMENTS_WITH_EVIDENCE": p.documents_with_evidence,
    "DB_DOCUMENTS_WITH_EVIDENCE": len(db_useful_doc_ids),
    "UI_EVIDENCE_COUNT": p.evidence_count,
    "DB_EVIDENCE_COUNT": len(e_rows),
    "UI_CATEGORY_CODES": p.category_codes,
    "DB_CATEGORY_CODES": db_cat_codes,
    "UI_SOURCE_DOCUMENT_IDS_WITH_EVIDENCE": db_useful_doc_ids,
    "DB_SOURCE_DOCUMENT_IDS_WITH_EVIDENCE": db_useful_doc_ids,
}

print(json.dumps(result, indent=2))
