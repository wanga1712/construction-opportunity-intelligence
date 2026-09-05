import psycopg2, json
from src.services.commercial_routing_v3.research_ui_projection import load_research_ui_projection, format_friendly_locator

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

pids = [150194, 149969, 149963]
projs = load_research_ui_projection(pids, crm_db, doc_db)

out = {}
for pid, p in projs.items():
    out[pid] = {
        "procurement_id": p.procurement_id,
        "research_state": p.research_state,
        "documents_total": p.documents_total,
        "documents_with_evidence": p.documents_with_evidence,
        "documents_no_evidence": p.documents_no_evidence,
        "documents_unknown": p.documents_unknown,
        "evidence_count": p.evidence_count,
        "category_codes": p.category_codes,
        "category_names": p.category_names,
        "top_matched_terms": p.top_matched_terms,
        "truth_completeness": p.truth_completeness,
    }

print("PROJECTION RESULT:")
print(json.dumps(out, indent=2, default=str))

loc1 = format_friendly_locator({"sheet_name": "Оборудование", "row_number": 42, "page_number": 17})
loc2 = format_friendly_locator({"archive_member_path": "sub/spec.doc", "row_number": 8})
print("FRIENDLY LOCATOR 1:", loc1)
print("FRIENDLY LOCATOR 2:", loc2)
