import json
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
