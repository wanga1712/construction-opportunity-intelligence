"""Procurement timeline (arrival → statuses → medals → model runs → UI labels)
plus the exact model prompt text. Read-only, defensive per source."""
from __future__ import annotations

from typing import Any, Dict, List


def _rows(crm_db: Any, sql: str, params: tuple) -> List[Dict[str, Any]]:
    try:
        return [dict(r) for r in (crm_db.execute_query(sql, params) or [])]
    except Exception:
        return []


def load_history(crm_db: Any, procurement_id: int) -> Dict[str, Any]:
    pid = int(procurement_id)
    proc = _rows(crm_db, """
        SELECT id, contract_number, source_table, crm_stage, award_status,
               crm_created_at, crm_updated_at, start_date, end_date, deadline_trust
        FROM crm_procurements WHERE id=%s""", (pid,))
    return {
        "procurement": proc[0] if proc else {},
        "medal_history": _rows(crm_db, """
            SELECT * FROM crm_category_opportunity_medal_history
            WHERE procurement_id=%s ORDER BY id""", (pid,)),
        "lifecycle": _rows(crm_db, """
            SELECT old_source_event, new_source_event, reason, source_seen_at
            FROM crm_category_opportunity_lifecycle_audit
            WHERE procurement_id=%s ORDER BY id""", (pid,)),
        "assessments": _rows(crm_db, """
            SELECT * FROM procurement_ai_assessments
            WHERE procurement_id=%s ORDER BY id""", (pid,)),
        "manual": _rows(crm_db, """
            SELECT * FROM crm_manual_assessments_audit
            WHERE procurement_id=%s ORDER BY id""", (pid,)),
        "feedback": _rows(crm_db, """
            SELECT category_code, polarity, label_source, created_at
            FROM crm_ui_feedback WHERE procurement_id=%s ORDER BY id""", (pid,)),
    }


def load_model_prompt(crm_db: Any, procurement_id: int) -> Dict[str, Any]:
    """Return the model_input payload and the exact V3 prompt the model receives.

    Reuses the production path: ``build_v3_prompt`` with the same registry,
    OKPD priors, routing signals and procurement-form prior that
    ``CommercialRoutingV3Engine.build_prompt_context`` feeds to the model.
    """
    from src.services.inference_job_queue import canonical_input_identity
    ident = canonical_input_identity(crm_db, int(procurement_id))
    model_input = ident.get("model_input") if isinstance(ident, dict) else None
    prompt = None
    if isinstance(model_input, dict):
        try:
            from src.services.commercial_routing_v3.engine import CommercialRoutingV3Engine
            from src.services.commercial_routing_v3.model_input import (
                model_input_as_prompt_procurement,
            )
            engine = CommercialRoutingV3Engine(crm_db)
            procurement = model_input_as_prompt_procurement(model_input)
            prompt = engine.build_prompt_context(procurement)
        except Exception:
            prompt = None
    return {"result": ident.get("result") if isinstance(ident, dict) else None,
            "model_input": model_input, "prompt": prompt}


def timeline_lines(history: Dict[str, Any]) -> List[str]:
    """Human-readable timeline lines for the card."""
    lines: List[str] = []
    proc = history.get("procurement") or {}
    if proc:
        lines.append(f"{proc.get('crm_created_at')}: поступила "
                     f"({proc.get('source_table')}, №{proc.get('contract_number')})")
        lines.append(f"сейчас: stage={proc.get('crm_stage')}, status={proc.get('award_status')}, "
                     f"deadline_trust={proc.get('deadline_trust')}")
    for row in history.get("lifecycle") or []:
        lines.append(f"{row.get('source_seen_at')}: статус {row.get('old_source_event')} → "
                     f"{row.get('new_source_event')} ({row.get('reason')})")
    for row in history.get("medal_history") or []:
        lines.append(f"{row.get('evaluated_at') or row.get('created_at')}: медаль "
                     f"{row.get('previous_effective_medal')} → {row.get('new_effective_medal')} "
                     f"({row.get('reason')})")
    for row in history.get("manual") or []:
        lines.append(f"{row.get('created_at') or row.get('at')}: ручная правка медали")
    for row in history.get("feedback") or []:
        lines.append(f"{row.get('created_at')}: метка {row.get('polarity')} "
                     f"по категории {row.get('category_code')}")
    return lines
