import psycopg2, psycopg2.extras, json
from src.services.annotation_queue_service import fetch_procurement_header
from src.services.commercial_routing_v3.document_links import resolve_document_links
from src.services.annotation_card_view import load_current_generation_raw_evidence

crm_conn = psycopg2.connect("dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432")

with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.execute("SELECT * FROM crm_v3_raw_source_evidence WHERE procurement_id = 160646")
    ev_rows = cur.fetchall()

header = fetch_procurement_header(None, 160646) if False else {}

print("RAW EVIDENCE ROWS FOR 160646:")
print(json.dumps([dict(r) for r in ev_rows], indent=2, default=str))
crm_conn.close()
