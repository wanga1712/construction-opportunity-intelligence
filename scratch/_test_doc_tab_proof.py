import psycopg2, psycopg2.extras, json
from src.services.annotation_queue_service import fetch_procurement_header
from src.services.commercial_routing_v3.document_links import resolve_document_links
from src.services.annotation_card_view import compose_annotation_card_view, load_current_generation_raw_evidence

class DummyDB:
    def __init__(self, conn):
        self.conn = conn
    def execute_query(self, query, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return [dict(r) for r in cur.fetchall()]

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")
crm_db = DummyDB(crm_conn)

header = fetch_procurement_header(crm_db, 150194)
resolved = resolve_document_links(
    source_table=header.get("source_table") or "",
    source_id=header.get("source_id"),
    contract_number=header.get("contract_number"),
    limit=10000,
)
raw_ev = load_current_generation_raw_evidence(150194, crm_db)
card_view = compose_annotation_card_view(
    header=header,
    resolved=resolved,
    observations=[],
    history=[],
    raw_evidence=raw_ev,
)

doc_proof = {
    "PROCUREMENT_ID": 150194,
    "DOCUMENTS_COUNT": len(card_view["documents"]),
    "ALL_DOCUMENTS_VISIBLE": len(card_view["documents"]) == 10,
    "DOWNLOAD_LINK_VISIBLE": any(bool(d.get("document_url")) for d in card_view["documents"]),
    "EVIDENCE_DOCUMENT_JOIN": "source_document_id",
    "LOCATOR_VISIBLE": any(bool(ev.get("friendly_locator")) for d in card_view["documents"] for ev in d.get("research_evidence") or []),
    "RAW_FRAGMENT_VISIBLE": any(bool(ev.get("raw_text")) for d in card_view["documents"] for ev in d.get("research_evidence") or []),
    "SAMPLE_DOCUMENTS": [
        {
            "name": d.get("document_name"),
            "url": d.get("document_url"),
            "evidence_count": len(d.get("research_evidence") or []),
            "locators": [ev.get("friendly_locator") for ev in (d.get("research_evidence") or [])],
        }
        for d in card_view["documents"][:3]
    ]
}

print(json.dumps(doc_proof, indent=2))
crm_conn.close()
