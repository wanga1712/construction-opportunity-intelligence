#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_st = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/card_research_state.py"
code_st = '''import hashlib, psycopg2, psycopg2.extras
from typing import Any, Dict, List, Optional
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
) -> Dict[str, Any]:
    doc_res = resolve_document_links(
        source_table=source_table or "",
        source_id=source_id,
        contract_number=contract_number or "",
    )
    links = doc_res.get("links") or []
    canonical_doc_count = len(links)
    gen_hash = compute_research_generation_hash(procurement_id, links, pipeline_generation)

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
            cur.execute(
                """
                SELECT status, created_at, completed_at
                FROM document_processing_queue
                WHERE procurement_id = %s AND pipeline_generation = %s
                ORDER BY id DESC LIMIT 1
                """,
                (procurement_id, pipeline_generation),
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
    elif queue_status in ("PENDING", "RUNNING", "RETRY"):
        state = STATE_RESEARCHING
    elif queue_status == "FAILED" or (documents_discovered > 0 and doc_failed == documents_discovered):
        state = STATE_FAILED
    elif documents_discovered > 0 and (doc_failed > 0 or doc_unsupported > 0 or uncertain_findings_count > 0) and doc_researched < documents_discovered:
        state = STATE_PARTIAL
    elif queue_status == "COMPLETED" and documents_discovered > 0 and doc_researched >= documents_discovered and doc_failed == 0 and uncertain_findings_count == 0:
        state = STATE_NO_EVIDENCE
    elif queue_status in ("COMPLETED", "SKIPPED"):
        state = STATE_PARTIAL if (doc_failed > 0 or doc_unsupported > 0 or uncertain_findings_count > 0) else STATE_NO_EVIDENCE
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
        "research_generation": gen_hash,
    }
'''

with open(path_st, "w", encoding="utf-8") as f:
    f.write(code_st)

path_svc = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/canonical_card_service.py"
code_svc = '''import json
from typing import Any, Dict, List, Optional
from src.services.commercial_routing_v3.card_research_state import (
    STATE_EVIDENCE_FOUND,
    STATE_FAILED,
    STATE_NO_EVIDENCE,
    STATE_PARTIAL,
    STATE_RESEARCHING,
    STATE_WAITING_RESEARCH,
    VALID_RESEARCH_STATES,
    derive_procurement_research_state,
)
from src.services.commercial_routing_v3.submission_window import actionable_submission_sql

def get_torgi_workset_predicate(alias: str = "p") -> str:
    return f"{alias}.crm_stage = 'torgi' AND {alias}.award_status = 'submission_open' AND {actionable_submission_sql(alias)}"

def sync_procurement_card_projection(procurement_id: int, crm_db) -> Dict[str, Any]:
    p_rows = crm_db.execute_query("SELECT id, source_table, source_id, contract_number FROM crm_procurements WHERE id = %s", (procurement_id,))
    p_fact = p_rows[0] if p_rows else {}

    metrics = derive_procurement_research_state(
        procurement_id,
        crm_db,
        source_table=p_fact.get("source_table"),
        source_id=p_fact.get("source_id"),
        contract_number=p_fact.get("contract_number"),
    )

    card_json = {
        "procurement_id": procurement_id,
        "source_table": p_fact.get("source_table"),
        "source_id": p_fact.get("source_id"),
        "contract_number": p_fact.get("contract_number"),
        "research_metrics": metrics,
    }

    sql = """
        INSERT INTO crm_v3_canonical_procurement_cards (
            procurement_id, card_json, card_version, research_state,
            documents_discovered, documents_supported, documents_researched,
            documents_failed, documents_unsupported, documents_no_content,
            raw_evidence_count, accepted_evidence_count, normalized_findings_count,
            documents_with_evidence, preliminary_research_priority,
            research_started_at, research_completed_at, research_generation,
            updated_at
        ) VALUES (
            %s, %s, 'V3_RESEARCH', %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            NOW()
        )
        ON CONFLICT (procurement_id) DO UPDATE SET
            card_json = EXCLUDED.card_json,
            research_state = EXCLUDED.research_state,
            documents_discovered = EXCLUDED.documents_discovered,
            documents_supported = EXCLUDED.documents_supported,
            documents_researched = EXCLUDED.documents_researched,
            documents_failed = EXCLUDED.documents_failed,
            documents_unsupported = EXCLUDED.documents_unsupported,
            documents_no_content = EXCLUDED.documents_no_content,
            raw_evidence_count = EXCLUDED.raw_evidence_count,
            accepted_evidence_count = EXCLUDED.accepted_evidence_count,
            normalized_findings_count = EXCLUDED.normalized_findings_count,
            documents_with_evidence = EXCLUDED.documents_with_evidence,
            preliminary_research_priority = EXCLUDED.preliminary_research_priority,
            research_started_at = EXCLUDED.research_started_at,
            research_completed_at = EXCLUDED.research_completed_at,
            research_generation = EXCLUDED.research_generation,
            updated_at = NOW()
        RETURNING procurement_id, research_state
    """

    crm_db.execute_query(
        sql,
        (
            procurement_id,
            json.dumps(card_json, ensure_ascii=False, default=str),
            metrics["research_state"],
            metrics["documents_discovered"],
            metrics["documents_supported"],
            metrics["documents_researched"],
            metrics["documents_failed"],
            metrics["documents_unsupported"],
            metrics["documents_no_content"],
            metrics["raw_evidence_count"],
            metrics["accepted_evidence_count"],
            metrics["normalized_findings_count"],
            metrics["documents_with_evidence"],
            metrics["preliminary_research_priority"],
            metrics["research_started_at"],
            metrics["research_completed_at"],
            metrics["research_generation"],
        ),
    )
    return metrics

def get_master_procurement_list_filtered(
    crm_db,
    research_state_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    pred = get_torgi_workset_predicate("p")
    if research_state_filter and research_state_filter.upper() != "ALL":
        st = research_state_filter.upper()
        if st in VALID_RESEARCH_STATES:
            sql = f"""
                SELECT p.id AS procurement_id, p.source_table, p.contract_number,
                       COALESCE(c.research_state, 'WAITING_RESEARCH') AS research_state,
                       COALESCE(c.documents_discovered, 0) AS documents_discovered,
                       COALESCE(c.documents_researched, 0) AS documents_researched,
                       COALESCE(c.documents_failed, 0) AS documents_failed,
                       COALESCE(c.raw_evidence_count, 0) AS raw_evidence_count,
                       COALESCE(c.normalized_findings_count, 0) AS normalized_findings_count,
                       COALESCE(c.preliminary_research_priority, 'UNSCORED') AS preliminary_research_priority,
                       c.updated_at
                FROM crm_procurements p
                LEFT JOIN crm_v3_canonical_procurement_cards c ON c.procurement_id = p.id
                WHERE {pred}
                  AND COALESCE(c.research_state, 'WAITING_RESEARCH') = %s
                ORDER BY p.id DESC
                LIMIT %s OFFSET %s
            """
            rows = crm_db.execute_query(sql, (st, limit, offset)) or []
            return [dict(r) for r in rows]

    sql = f"""
        SELECT p.id AS procurement_id, p.source_table, p.contract_number,
               COALESCE(c.research_state, 'WAITING_RESEARCH') AS research_state,
               COALESCE(c.documents_discovered, 0) AS documents_discovered,
               COALESCE(c.documents_researched, 0) AS documents_researched,
               COALESCE(c.documents_failed, 0) AS documents_failed,
               COALESCE(c.raw_evidence_count, 0) AS raw_evidence_count,
               COALESCE(c.normalized_findings_count, 0) AS normalized_findings_count,
               COALESCE(c.preliminary_research_priority, 'UNSCORED') AS preliminary_research_priority,
               c.updated_at
        FROM crm_procurements p
        LEFT JOIN crm_v3_canonical_procurement_cards c ON c.procurement_id = p.id
        WHERE {pred}
        ORDER BY p.id DESC
        LIMIT %s OFFSET %s
    """
    rows = crm_db.execute_query(sql, (limit, offset)) or []
    return [dict(r) for r in rows]

def get_research_state_counts(crm_db) -> Dict[str, Any]:
    pred = get_torgi_workset_predicate("p")
    sql = f"""
        SELECT COALESCE(c.research_state, 'WAITING_RESEARCH') AS research_state, COUNT(*) as cnt
        FROM crm_procurements p
        LEFT JOIN crm_v3_canonical_procurement_cards c ON c.procurement_id = p.id
        WHERE {pred}
        GROUP BY COALESCE(c.research_state, 'WAITING_RESEARCH')
    """
    rows = crm_db.execute_query(sql) or []
    counts_map = {r["research_state"]: int(r["cnt"]) for r in rows}

    waiting = counts_map.get(STATE_WAITING_RESEARCH, 0)
    researching = counts_map.get(STATE_RESEARCHING, 0)
    evidence_found = counts_map.get(STATE_EVIDENCE_FOUND, 0)
    no_evidence = counts_map.get(STATE_NO_EVIDENCE, 0)
    partial = counts_map.get(STATE_PARTIAL, 0)
    failed = counts_map.get(STATE_FAILED, 0)

    accepted_torgi_query_total = crm_db.execute_query(
        f"SELECT COUNT(*) as cnt FROM crm_procurements p WHERE {pred}"
    )[0]["cnt"]
    sum_parts = waiting + researching + evidence_found + no_evidence + partial + failed

    return {
        "ACCEPTED_TORGI_QUERY_TOTAL": accepted_torgi_query_total,
        "RESEARCH_ALL": accepted_torgi_query_total,
        "RESEARCH_WAITING": waiting,
        "RESEARCH_RESEARCHING": researching,
        "RESEARCH_EVIDENCE_FOUND": evidence_found,
        "RESEARCH_NO_EVIDENCE": no_evidence,
        "RESEARCH_PARTIAL": partial,
        "RESEARCH_FAILED": failed,
        "ONE_EFFECTIVE_RESEARCH_STATE_PER_PROCUREMENT": True,
        "RESEARCH_STATE_COUNTS_RECONCILE": (accepted_torgi_query_total == sum_parts),
    }
'''

with open(path_svc, "w", encoding="utf-8") as f:
    f.write(code_svc)

print("DEPLOYED STRICT DOCUMENT-SET GENERATION & SUBMISSION WINDOW PREDICATE TO S13!")

PYEOF
