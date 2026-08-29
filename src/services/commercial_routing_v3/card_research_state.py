import hashlib, os, psycopg2, psycopg2.extras
from typing import Any, Dict, List, Optional
from src.services.commercial_routing_v3.document_links import resolve_document_links

PIPELINE_GENERATION = "S13_V3_EXHAUSTIVE_CONTEXT"

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

def _get_doc_db_conn():
    from dotenv import load_dotenv
    try:
        load_dotenv("/opt/CRM_Streamlit/.env")
    except Exception:
        pass
    try:
        load_dotenv("/etc/crm_v3.env")
    except Exception:
        pass
    user = os.getenv("S13_DOCUMENT_DB_USER") or "doc_worker"
    password = os.getenv("S13_DOCUMENT_DB_PASSWORD") or "F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT"
    dsn = {
        "host": os.getenv("S13_DOCUMENT_DB_HOST") if os.getenv("S13_DOCUMENT_DB_HOST") not in (None, "", "S7") else "127.0.0.1",
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT") or os.getenv("CRM_DB_PORT") or "5432"),
        "dbname": "document_intelligence",
        "user": user,
        "password": password,
    }
    return psycopg2.connect(**dsn)

def compute_document_set_hash(canonical_links: List[Dict[str, Any]]) -> str:
    identities = []
    for link in canonical_links:
        sid = str(link.get("source_document_id") or link.get("id") or "").strip()
        url = str(link.get("canonical_url") or link.get("url") or link.get("document_url") or "").strip()
        name = str(link.get("document_name") or link.get("name") or "").strip()
        identities.append(f"{sid}|{url}|{name}")
    identities.sort()
    payload = "::".join(identities)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def compute_research_generation_hash(
    procurement_id: int,
    canonical_links: List[Dict[str, Any]],
    pipeline_generation: str = PIPELINE_GENERATION,
) -> str:
    doc_set_hash = compute_document_set_hash(canonical_links)
    payload = f"{procurement_id}||{doc_set_hash}||{pipeline_generation}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

def derive_procurement_research_state(
    procurement_id: int,
    crm_db,
    pipeline_generation: str = PIPELINE_GENERATION,
    source_table: Optional[str] = None,
    source_id: Optional[int] = None,
    contract_number: Optional[str] = None,
    canonical_links: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if canonical_links is None:
        try:
            doc_res = resolve_document_links(
                source_table=source_table or "",
                source_id=source_id,
                contract_number=contract_number or "",
            )
            canonical_links = doc_res.get("links") or []
        except Exception:
            canonical_links = []

    canonical_doc_count = len(canonical_links)
    gen_hash = compute_research_generation_hash(procurement_id, canonical_links, pipeline_generation)

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
            # PIPELINE_ONLY_QUEUE_ROW_COUNTS_AS_CURRENT = NO
            cur.execute(
                """
                SELECT status, created_at, completed_at
                FROM document_processing_queue
                WHERE procurement_id = %s
                  AND pipeline_generation = %s
                  AND research_generation_hash = %s
                ORDER BY id DESC LIMIT 1
                """,
                (procurement_id, pipeline_generation, gen_hash),
            )
            q_row = cur.fetchone()
            if q_row:
                queue_status = q_row["status"]
                task_created_at = q_row["created_at"]
                task_completed_at = q_row["completed_at"]

            cur.execute(
                """
                SELECT f.id, f.download_status, r.status AS parse_status
                FROM document_files f
                LEFT JOIN document_processing_results r ON r.file_id = f.id
                WHERE f.procurement_id = %s
                """,
                (procurement_id,),
            )
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

    raw_ev_rows = crm_db.execute_query(
        """
        SELECT COUNT(*) as cnt
        FROM crm_v3_raw_source_evidence
        WHERE procurement_id = %s AND research_generation_hash = %s
        """,
        (procurement_id, gen_hash),
    )
    raw_evidence_count = int(raw_ev_rows[0]["cnt"]) if raw_ev_rows else 0

    find_rows = crm_db.execute_query(
        """
        SELECT
            COUNT(*) as total_cnt,
            COUNT(*) FILTER (WHERE relevance = 'RELEVANT' AND raw_evidence_id IS NOT NULL) as accepted_cnt,
            COUNT(*) FILTER (WHERE relevance = 'UNCERTAIN') as uncertain_cnt
        FROM crm_v3_product_findings
        WHERE procurement_id = %s AND research_generation_hash = %s
        """,
        (procurement_id, gen_hash),
    )
    normalized_findings_count = int(find_rows[0]["total_cnt"]) if find_rows else 0
    accepted_evidence_count = int(find_rows[0]["accepted_cnt"]) if find_rows else 0
    uncertain_findings_count = int(find_rows[0]["uncertain_cnt"]) if find_rows else 0

    doc_ev_rows = crm_db.execute_query(
        "SELECT COUNT(DISTINCT source_document_id) as cnt FROM crm_v3_raw_source_evidence WHERE procurement_id = %s AND research_generation_hash = %s",
        (procurement_id, gen_hash),
    )
    documents_with_evidence = int(doc_ev_rows[0]["cnt"]) if doc_ev_rows else 0

    if accepted_evidence_count > 0:
        state = STATE_EVIDENCE_FOUND
    elif queue_status in ("PENDING", "PROCESSING", "RUNNING", "RETRY"):
        state = STATE_RESEARCHING
    elif queue_status == "FAILED" or (documents_discovered > 0 and doc_failed == documents_discovered):
        state = STATE_FAILED
    elif documents_discovered > 0 and doc_researched < documents_discovered:
        if doc_failed > 0 or doc_unsupported > 0 or uncertain_findings_count > 0:
            state = STATE_PARTIAL
        else:
            state = STATE_WAITING_RESEARCH
    elif documents_discovered > 0 and doc_researched >= documents_discovered and doc_failed == 0 and doc_unsupported == 0 and uncertain_findings_count == 0:
        state = STATE_NO_EVIDENCE
    else:
        state = STATE_PARTIAL if (doc_failed > 0 or doc_unsupported > 0 or uncertain_findings_count > 0) else STATE_WAITING_RESEARCH

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
        "research_generation": gen_hash,
    }
