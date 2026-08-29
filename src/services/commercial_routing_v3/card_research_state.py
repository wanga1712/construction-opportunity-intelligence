from typing import Any, Dict, List, Optional, Tuple
import psycopg2, psycopg2.extras
from src.services.commercial_routing_v3.document_links import resolve_document_links
from src.services.commercial_routing_v3.factual_feeder import _get_doc_db_conn, PIPELINE_GENERATION

STATE_WAITING_RESEARCH = "WAITING_RESEARCH"
STATE_RESEARCHING = "RESEARCHING"
STATE_EVIDENCE_FOUND = "EVIDENCE_FOUND"
STATE_NO_EVIDENCE = "NO_EVIDENCE"
STATE_PARTIAL = "PARTIAL"
STATE_FAILED = "FAILED"

VALID_RESEARCH_STATES = {
    STATE_WAITING_RESEARCH,
    STATE_RESEARCHING,
    STATE_EVIDENCE_FOUND,
    STATE_NO_EVIDENCE,
    STATE_PARTIAL,
    STATE_FAILED,
}

def derive_procurement_research_state(
    procurement_id: int,
    crm_db,
    pipeline_generation: str = PIPELINE_GENERATION,
    source_table: Optional[str] = None,
    source_id: Optional[int] = None,
    contract_number: Optional[str] = None,
) -> Dict[str, Any]:
    doc_res = resolve_document_links(
        source_table=source_table or "",
        source_id=source_id,
        contract_number=contract_number or "",
    )
    links = doc_res.get("links") or []
    canonical_doc_count = len(links)

    raw_ev_rows = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_raw_source_evidence WHERE procurement_id = %s", (procurement_id,))
    raw_evidence_count = int(raw_ev_rows[0]["cnt"]) if raw_ev_rows else 0

    find_rows = crm_db.execute_query(
        "SELECT COUNT(*) as total_cnt, COUNT(*) FILTER (WHERE category_validation_status != 'REJECTED_IRRELEVANT') as accepted_cnt FROM crm_v3_product_findings WHERE procurement_id = %s",
        (procurement_id,),
    )
    normalized_findings_count = int(find_rows[0]["total_cnt"]) if find_rows else 0
    accepted_evidence_count = int(find_rows[0]["accepted_cnt"]) if find_rows else 0

    doc_ev_rows = crm_db.execute_query("SELECT COUNT(DISTINCT source_document_id) as cnt FROM crm_v3_raw_source_evidence WHERE procurement_id = %s", (procurement_id,))
    documents_with_evidence = int(doc_ev_rows[0]["cnt"]) if doc_ev_rows else 0

    conn = _get_doc_db_conn()
    doc_files_count = 0
    doc_supported = 0
    doc_researched = 0
    doc_failed = 0
    doc_unsupported = 0
    doc_no_content = 0
    queue_status = None
    task_created_at = None
    task_completed_at = None

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT status, created_at, completed_at FROM document_processing_queue WHERE procurement_id = %s AND pipeline_generation = %s ORDER BY id DESC LIMIT 1", (procurement_id, pipeline_generation))
            q_row = cur.fetchone()
            if q_row:
                queue_status = q_row["status"]
                task_created_at = q_row["created_at"]
                task_completed_at = q_row["completed_at"]

            cur.execute("SELECT f.id, f.download_status, r.status AS parse_status FROM document_files f LEFT JOIN document_processing_results r ON r.file_id = f.id WHERE f.procurement_id = %s", (procurement_id,))
            f_rows = cur.fetchall() or []
            doc_files_count = len(f_rows)

            for fr in f_rows:
                dl = fr.get("download_status")
                prs = fr.get("parse_status")
                if dl == "FAILED": doc_failed += 1
                elif dl == "SKIPPED" or prs in ("UNSUPPORTED", "UNSUPPORTED_FORMAT"): doc_unsupported += 1
                elif prs in ("FAILED", "PARSE_FAILED"): doc_failed += 1
                elif prs in ("EMPTY", "EMPTY_DOCUMENT"):
                    doc_no_content += 1
                    doc_researched += 1
                    doc_supported += 1
                elif prs in ("COMPLETED", "PARSED_OK", "SUCCESS"):
                    doc_supported += 1
                    doc_researched += 1
    finally:
        conn.close()

    documents_discovered = max(canonical_doc_count, doc_files_count)

    if accepted_evidence_count > 0:
        state = STATE_EVIDENCE_FOUND
    elif queue_status in ("PENDING", "RUNNING", "RETRY"):
        state = STATE_RESEARCHING
    elif queue_status == "FAILED" or (documents_discovered > 0 and doc_failed == documents_discovered):
        state = STATE_FAILED
    elif documents_discovered > 0 and (doc_failed > 0 or doc_unsupported > 0) and doc_researched < documents_discovered:
        state = STATE_PARTIAL
    elif queue_status == "COMPLETED" and documents_discovered > 0 and doc_researched >= documents_discovered and doc_failed == 0:
        state = STATE_NO_EVIDENCE
    elif queue_status in ("COMPLETED", "SKIPPED"):
        state = STATE_PARTIAL if (doc_failed > 0 or doc_unsupported > 0) else STATE_NO_EVIDENCE
    else:
        state = STATE_WAITING_RESEARCH

    return {
        "procurement_id": procurement_id,
        "research_state": state,
        "documents_discovered": documents_discovered,
        "documents_supported": doc_supported,
        "documents_researched": doc_researched,
        "documents_failed": doc_failed,
        "documents_unsupported": doc_unsupported,
        "documents_no_content": doc_no_content,
        "raw_evidence_count": raw_evidence_count,
        "accepted_evidence_count": accepted_evidence_count,
        "normalized_findings_count": normalized_findings_count,
        "documents_with_evidence": documents_with_evidence,
        "preliminary_research_priority": "UNSCORED",
        "research_started_at": task_created_at,
        "research_completed_at": task_completed_at,
        "research_generation": pipeline_generation,
    }
