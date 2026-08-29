from typing import Any, Dict, List, Optional
import json
from src.services.commercial_routing_v3.card_research_state import (
    STATE_EVIDENCE_FOUND,
    STATE_FAILED,
    STATE_NO_EVIDENCE,
    STATE_PARTIAL,
    STATE_RESEARCHING,
    STATE_WAITING_RESEARCH,
    VALID_RESEARCH_STATES,
    derive_procurement_research_state,
    PIPELINE_GENERATION,
)
from src.services.commercial_routing_v3.submission_window import actionable_submission_sql

def get_torgi_workset_predicate(prefix: str = "p") -> str:
    return f"{prefix}.crm_stage = 'torgi' AND {prefix}.award_status = 'submission_open' AND {actionable_submission_sql(prefix)}"

def sync_procurement_card_projection(
    procurement_id: int,
    crm_db: Any,
    pipeline_generation: str = PIPELINE_GENERATION,
    canonical_links: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    state_info = derive_procurement_research_state(
        procurement_id,
        crm_db,
        pipeline_generation=pipeline_generation,
        canonical_links=canonical_links,
    )
    card_json_str = json.dumps(state_info, default=str, ensure_ascii=False)
    
    crm_db.execute_update(
        """
        INSERT INTO crm_v3_canonical_procurement_cards (
            procurement_id, card_json, research_state, documents_discovered, documents_supported,
            documents_researched, documents_failed, documents_unsupported, documents_no_content,
            raw_evidence_count, accepted_evidence_count, normalized_findings_count,
            documents_with_evidence, preliminary_research_priority, research_started_at,
            research_completed_at, research_generation, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
        """,
        (
            state_info["procurement_id"],
            card_json_str,
            state_info["research_state"],
            state_info["documents_discovered"],
            state_info["documents_supported"],
            state_info["documents_researched"],
            state_info["documents_failed"],
            state_info["documents_unsupported"],
            state_info["documents_no_content"],
            state_info["raw_evidence_count"],
            state_info["accepted_evidence_count"],
            state_info["normalized_findings_count"],
            state_info["documents_with_evidence"],
            state_info["preliminary_research_priority"],
            state_info["research_started_at"],
            state_info["research_completed_at"],
            state_info["research_generation"],
        ),
    )
    return state_info

def get_master_procurement_list_filtered(crm_db, research_state_filter: Optional[str] = None, page: int = 1, page_size: int = 25) -> Dict[str, Any]:
    pred = get_torgi_workset_predicate("p")
    where_clauses = [pred]
    params = []

    if research_state_filter and research_state_filter != "ALL":
        if research_state_filter in VALID_RESEARCH_STATES:
            where_clauses.append("COALESCE(prj.research_state, 'WAITING_RESEARCH') = %s")
            params.append(research_state_filter)

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * page_size

    cnt_rows = crm_db.execute_query(
        f"""
        SELECT COUNT(*) as total
        FROM crm_procurements p
        LEFT JOIN crm_v3_canonical_procurement_cards prj ON prj.procurement_id = p.id
        WHERE {where_sql}
        """,
        params
    )
    total_count = int(cnt_rows[0]["total"]) if cnt_rows else 0

    query_params = list(params) + [page_size, offset]
    items = crm_db.execute_query(
        f"""
        SELECT
            p.id, p.source_table, p.source_id, p.contract_number, p.object_info,
            p.price, p.customer_name, p.end_date, p.crm_stage, p.award_status,
            COALESCE(prj.research_state, 'WAITING_RESEARCH') as research_state,
            prj.accepted_evidence_count, prj.documents_discovered, prj.documents_researched,
            prj.research_generation
        FROM crm_procurements p
        LEFT JOIN crm_v3_canonical_procurement_cards prj ON prj.procurement_id = p.id
        WHERE {where_sql}
        ORDER BY p.id DESC
        LIMIT %s OFFSET %s
        """,
        query_params
    ) or []

    return {
        "total_count": total_count,
        "items": items,
        "page": page,
        "page_size": page_size,
    }

def get_research_state_counts(crm_db) -> Dict[str, Any]:
    pred = get_torgi_workset_predicate("p")
    rows = crm_db.execute_query(
        f"""
        SELECT
            COUNT(*) as total_workset,
            COUNT(*) FILTER (WHERE COALESCE(prj.research_state, 'WAITING_RESEARCH') = 'WAITING_RESEARCH') as cnt_waiting,
            COUNT(*) FILTER (WHERE prj.research_state = 'RESEARCHING') as cnt_researching,
            COUNT(*) FILTER (WHERE prj.research_state = 'EVIDENCE_FOUND') as cnt_evidence_found,
            COUNT(*) FILTER (WHERE prj.research_state = 'NO_EVIDENCE') as cnt_no_evidence,
            COUNT(*) FILTER (WHERE prj.research_state = 'PARTIAL') as cnt_partial,
            COUNT(*) FILTER (WHERE prj.research_state = 'FAILED') as cnt_failed
        FROM crm_procurements p
        LEFT JOIN crm_v3_canonical_procurement_cards prj ON prj.procurement_id = p.id
        WHERE {pred}
        """
    )
    r = rows[0] if rows else {}
    tot = int(r.get("total_workset") or 0)
    w = int(r.get("cnt_waiting") or 0)
    res = int(r.get("cnt_researching") or 0)
    ef = int(r.get("cnt_evidence_found") or 0)
    ne = int(r.get("cnt_no_evidence") or 0)
    part = int(r.get("cnt_partial") or 0)
    fa = int(r.get("cnt_failed") or 0)

    reconciles = (tot == (w + res + ef + ne + part + fa))

    return {
        "ACCEPTED_TORGI_QUERY_TOTAL": tot,
        "RESEARCH_ALL": tot,
        "RESEARCH_WAITING": w,
        "RESEARCH_RESEARCHING": res,
        "RESEARCH_EVIDENCE_FOUND": ef,
        "RESEARCH_NO_EVIDENCE": ne,
        "RESEARCH_PARTIAL": part,
        "RESEARCH_FAILED": fa,
        "ONE_EFFECTIVE_RESEARCH_STATE_PER_PROCUREMENT": True,
        "RESEARCH_STATE_COUNTS_RECONCILE": reconciles,
    }
