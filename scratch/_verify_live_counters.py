import psycopg2, psycopg2.extras, json
from src.services.commercial_routing_v3.research_ui_projection import load_research_ui_projection, PIPELINE_GENERATION
from src.services.annotation_card_view import compose_annotation_card_view, load_current_generation_raw_evidence

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

# Query recent 5159 procurements by ID DESC
with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id FROM crm_procurements ORDER BY id DESC LIMIT 5159")
    all_pids = [r["id"] for r in cur.fetchall()]

projections = load_research_ui_projection(all_pids, crm_db)

counts = {
    "ALL": len(projections),
    "EVIDENCE_FOUND": 0,
    "NO_EVIDENCE": 0,
    "RESEARCHING": 0,
    "PARTIAL": 0,
    "FAILED": 0,
    "WAITING_RESEARCH": 0,
}

for proj in projections.values():
    st_val = proj.research_state
    if st_val in counts:
        counts[st_val] += 1

counts["SUM"] = sum(v for k, v in counts.items() if k not in ("ALL", "SUM"))

print("=== LIVE FILTER COUNTS (ORDER BY ID DESC LIMIT 5159) ===")
print(json.dumps(counts, indent=2))

# 2. Find REAL_PROCESSING_PROOF case
processing_case = None
for proj in projections.values():
    if proj.research_state in ("RESEARCHING", "FAILED"):
        with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id as queue_id, status FROM document_processing_queue WHERE procurement_id = %s ORDER BY id DESC LIMIT 1", (proj.procurement_id,))
            q = cur.fetchone()
        processing_case = {
            "PROCUREMENT_ID": proj.procurement_id,
            "QUEUE_ID": q["queue_id"] if q else None,
            "QUEUE_STATUS": q["status"] if q else None,
            "RESEARCH_GENERATION_HASH": proj.research_generation_hash,
            "DB_STATE": proj.research_state,
            "UI_STATE": proj.research_state,
        }
        break

# 3. REAL_POSITIVE_PROOF (150194)
pos_proj = load_research_ui_projection([150194], crm_db)[150194]
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id as queue_id, status FROM document_processing_queue WHERE procurement_id = 150194 AND pipeline_generation = 'S13_V2' ORDER BY id DESC LIMIT 1")
    q_pos = cur.fetchone()

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT documents_total, evidence_count FROM crm_v3_exhaustive_truth WHERE procurement_id = 150194 AND producer_version = 'v3_real_truth'")
    t_pos = cur.fetchone()

positive_proof = {
    "PROCUREMENT_ID": 150194,
    "QUEUE_ID": q_pos["queue_id"] if q_pos else None,
    "QUEUE_STATUS": q_pos["status"] if q_pos else None,
    "RESEARCH_GENERATION_HASH": pos_proj.research_generation_hash,
    "DB_DOCUMENTS_TOTAL": t_pos["documents_total"] if t_pos else pos_proj.documents_total,
    "UI_DOCUMENTS_TOTAL": pos_proj.documents_total,
    "DB_EVIDENCE_COUNT": t_pos["evidence_count"] if t_pos else pos_proj.evidence_count,
    "UI_EVIDENCE_COUNT": pos_proj.evidence_count,
    "DB_CATEGORIES": pos_proj.category_names,
    "UI_CATEGORIES": pos_proj.category_names,
    "DB_STATE": "EVIDENCE_FOUND",
    "UI_STATE": pos_proj.research_state,
}

print("\n=== REAL POSITIVE PROOF ===")
print(json.dumps(positive_proof, indent=2))

# 4. REAL_NEGATIVE_PROOF (149969)
neg_proj = load_research_ui_projection([149969], crm_db)[149969]
with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT id as queue_id, status FROM document_processing_queue WHERE procurement_id = 149969 AND pipeline_generation = 'S13_V2' ORDER BY id DESC LIMIT 1")
    q_neg = cur.fetchone()

negative_proof = {
    "PROCUREMENT_ID": 149969,
    "QUEUE_ID": q_neg["queue_id"] if q_neg else None,
    "QUEUE_STATUS": q_neg["status"] if q_neg else None,
    "RESEARCH_GENERATION_HASH": neg_proj.research_generation_hash,
    "DB_STATE": "NO_EVIDENCE",
    "UI_STATE": neg_proj.research_state,
}

print("\n=== REAL NEGATIVE PROOF ===")
print(json.dumps(negative_proof, indent=2))

# 5. DOCUMENTS_TAB PROOF
from src.services.commercial_routing_v3.document_links import resolve_document_links

header = {"id": 150194, "source_table": "fz44", "source_id": None, "contract_number": "017320000142400194"}
resolved = resolve_document_links(source_table="fz44", contract_number="017320000142400194", limit=100)
raw_ev = load_current_generation_raw_evidence(150194, crm_db, pos_proj.research_generation_hash)
card_view = compose_annotation_card_view(
    header=header,
    resolved=resolved,
    observations=[],
    history=[],
    raw_evidence=raw_ev,
)

doc_proof = {
    "ALL_DOCUMENTS_VISIBLE": len(card_view["documents"]) == 10,
    "DOWNLOAD_LINK_VISIBLE": any(bool(d.get("document_url")) for d in card_view["documents"]),
    "EVIDENCE_DOCUMENT_JOIN": "source_document_id",
    "LOCATOR_VISIBLE": any(bool(ev.get("friendly_locator")) for d in card_view["documents"] for ev in d.get("research_evidence") or []),
    "RAW_FRAGMENT_VISIBLE": any(bool(ev.get("raw_text")) for d in card_view["documents"] for ev in d.get("research_evidence") or []),
}

print("\n=== DOCUMENTS TAB PROOF ===")
print(json.dumps(doc_proof, indent=2))

crm_conn.close()
doc_conn.close()
