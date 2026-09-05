#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
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

def sync_procurement_card_projection(procurement_id: int, crm_db) -> Dict[str, Any]:
    metrics = derive_procurement_research_state(procurement_id, crm_db)
    p_rows = crm_db.execute_query("SELECT id, source_table, source_id, contract_number FROM crm_procurements WHERE id = %s", (procurement_id,))
    p_fact = p_rows[0] if p_rows else {}

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
    if research_state_filter and research_state_filter.upper() != "ALL":
        st = research_state_filter.upper()
        if st in VALID_RESEARCH_STATES:
            sql = """
                SELECT c.procurement_id, c.research_state, c.documents_discovered,
                       c.documents_researched, c.documents_failed, c.raw_evidence_count,
                       c.normalized_findings_count, c.preliminary_research_priority,
                       c.updated_at, p.source_table, p.contract_number
                FROM crm_v3_canonical_procurement_cards c
                JOIN crm_procurements p ON p.id = c.procurement_id
                WHERE c.research_state = %s
                ORDER BY c.procurement_id DESC
                LIMIT %s OFFSET %s
            """
            rows = crm_db.execute_query(sql, (st, limit, offset)) or []
            return [dict(r) for r in rows]

    sql = """
        SELECT c.procurement_id, c.research_state, c.documents_discovered,
               c.documents_researched, c.documents_failed, c.raw_evidence_count,
               c.normalized_findings_count, c.preliminary_research_priority,
               c.updated_at, p.source_table, p.contract_number
        FROM crm_v3_canonical_procurement_cards c
        JOIN crm_procurements p ON p.id = c.procurement_id
        ORDER BY c.procurement_id DESC
        LIMIT %s OFFSET %s
    """
    rows = crm_db.execute_query(sql, (limit, offset)) or []
    return [dict(r) for r in rows]

def get_research_state_counts(crm_db) -> Dict[str, Any]:
    sql = "SELECT research_state, COUNT(*) as cnt FROM crm_v3_canonical_procurement_cards GROUP BY research_state"
    rows = crm_db.execute_query(sql) or []
    counts_map = {r["research_state"]: int(r["cnt"]) for r in rows}

    waiting = counts_map.get(STATE_WAITING_RESEARCH, 0)
    researching = counts_map.get(STATE_RESEARCHING, 0)
    evidence_found = counts_map.get(STATE_EVIDENCE_FOUND, 0)
    no_evidence = counts_map.get(STATE_NO_EVIDENCE, 0)
    partial = counts_map.get(STATE_PARTIAL, 0)
    failed = counts_map.get(STATE_FAILED, 0)

    total_all = crm_db.execute_query("SELECT COUNT(*) as cnt FROM crm_v3_canonical_procurement_cards")[0]["cnt"]
    sum_parts = waiting + researching + evidence_found + no_evidence + partial + failed

    return {
        "RESEARCH_ALL": total_all,
        "RESEARCH_WAITING": waiting,
        "RESEARCH_RESEARCHING": researching,
        "RESEARCH_EVIDENCE_FOUND": evidence_found,
        "RESEARCH_NO_EVIDENCE": no_evidence,
        "RESEARCH_PARTIAL": partial,
        "RESEARCH_FAILED": failed,
        "ONE_EFFECTIVE_RESEARCH_STATE_PER_PROCUREMENT": True,
        "RESEARCH_STATE_COUNTS_RECONCILE": (total_all == sum_parts),
    }
'''

with open(path_svc, "w", encoding="utf-8") as f:
    f.write(code_svc)

print("UPDATED canonical_card_service.py!")
PYEOF
