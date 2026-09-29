"""Service for loading and querying prioritized procurement worksets for the Torgi stage.

Unified single-authority evaluation combining FirstPassService, expert annotations,
and source contour mappings with zero N+1 database roundtrips.
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.effective_medal_service import resolve_card_effective_medals
from src.services.first_pass.service import FirstPassService
from src.services.medal_semantics_v2 import is_model_authority_current
from src.services.source_contour import resolve_source_contour

logger = logging.getLogger(__name__)

MEDAL_RANKS = {"GOLD": 1, "SILVER": 2, "BRONZE": 3, "WOOD": 4, "UNASSESSED": 5}


@dataclass
class TorgiFilterParams:
    """Parameters for filtering active torgi worksets."""
    effective_medal: Optional[str] = None    # ALL, GOLD, SILVER, BRONZE, WOOD, UNASSESSED
    model_medal: Optional[str] = None        # ALL, GOLD, SILVER, BRONZE, WOOD, UNASSESSED
    preliminary_medal: Optional[str] = None  # ALL, GOLD, SILVER, BRONZE, WOOD, UNASSESSED
    expert_status: Optional[str] = None      # ALL, Подтверждено, Не проверено
    expert_medal: Optional[str] = None       # ALL, GOLD, SILVER, BRONZE, WOOD
    object_family: Optional[str] = None      # ALL, SOCIAL, COMMERCIAL, DIRECT_SUPPLY, OTHER
    object_type: Optional[str] = None
    category: Optional[str] = None
    law: Optional[str] = None                # ALL, 44, 223, 615
    region: Optional[str] = None
    search_query: Optional[str] = None
    hide_expired: bool = True                # Default: True (hide end_date < NOW() or closed)
    allowed_ids: Optional[Sequence[int]] = None



def _load_raw_torgi_records(hide_expired: bool = True) -> List[Dict[str, Any]]:
    """Fetch raw torgi procurement records and linked tables from CRM DB."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(**require_crm_db_connect_kwargs())
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if hide_expired:
                where = f"cp.crm_stage = 'torgi' AND cp.award_status = 'submission_open' AND {actionable_submission_sql('cp')}"
            else:
                where = "cp.crm_stage = 'torgi'"

            cur.execute(f"""
                SELECT cp.id, cp.contract_number, cp.auction_name, cp.initial_price, cp.customer, cp.delivery_region,
                       cp.okpd_code, cp.okpd_name, cp.crm_category, cp.contractor_name, cp.contractor_inn,
                       cp.match_score, cp.signal_score, cp.commercial_score, cp.processing_stage, cp.matched_keywords,
                       cp.file_count, cp.match_count, cp.evidence_count, cp.start_date, cp.end_date, cp.delivery_end_date,
                       cp.tender_link, cp.award_status, cp.crm_stage, cp.crm_profile_id, cp.source_table, cp.source_id,
                       cp.crm_created_at, cp.crm_updated_at, cp.source_updated_at,
                       cp.ai_assessment_status, cp.ai_assessment_version, cp.ai_assessment_stability, cp.ai_stability_count,
                       cp.object_type
                FROM crm_procurements cp
                WHERE {where}
                ORDER BY cp.id
            """)
            procs = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT id, procurement_id, candidate_medal, commercial_priority_score, commercial_category_code,
                       commercial_subcategory_code, confirmed_base_medal, status
                FROM crm_procurement_category_opportunities
                WHERE status = 'CURRENT'
            """)
            opp_by_pid: Dict[int, List[Dict[str, Any]]] = {}
            for o in cur.fetchall():
                opp_by_pid.setdefault(o["procurement_id"], []).append(dict(o))

            cur.execute("""
                SELECT a.procurement_id, a.proposed_level, a.confidence, a.proposed_object_type,
                       a.proposed_procurement_type, a.proposed_route_profile, a.reasons,
                       a.normalized_result, a.inference_run_id, a.prompt_version, a.is_stale,
                       r.run_kind, r.run_status, r.model_name
                FROM procurement_ai_assessments a
                LEFT JOIN crm_v3_model_inference_runs r ON r.id = a.inference_run_id
                WHERE a.is_current = TRUE
            """)
            ai_by_pid = {a["procurement_id"]: dict(a) for a in cur.fetchall()}

            cur.execute("""
                SELECT procurement_id, payload
                FROM crm_v3_expert_annotations
                WHERE is_current = TRUE
            """)
            ex_by_pid = {e["procurement_id"]: dict(e) for e in cur.fetchall()}

            cur.execute("""
                SELECT commercial_category_code, okpd_pattern, match_type, prior_weight, signal_role
                FROM crm_category_okpd_priors
                WHERE active = TRUE
            """)
            priors = [dict(r) for r in cur.fetchall()]

        return procs, opp_by_pid, ai_by_pid, ex_by_pid, priors
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def get_evaluated_torgi_workset(hide_expired: bool = True) -> List[Dict[str, Any]]:
    """Evaluate and canonicalize all active torgi procurements using First Pass."""
    procs, opp_by_pid, ai_by_pid, ex_by_pid, priors = _load_raw_torgi_records(hide_expired)
    service = FirstPassService(None)
    service._cached_priors = priors

    today_str = time.strftime("%Y-%m-%d")
    cards: List[Dict[str, Any]] = []

    for p in procs:
        pid = p["id"]
        ai = ai_by_pid.get(pid, {})
        p.update({
            "proposed_route_profile": ai.get("proposed_route_profile"),
            "proposed_object_type": ai.get("proposed_object_type"),
            "proposed_procurement_type": ai.get("proposed_procurement_type"),
            "confidence": ai.get("confidence"),
            "reasons": ai.get("reasons"),
            "normalized_result": ai.get("normalized_result"),
        })
        res = service.evaluate_procurement(
            proc=p,
            category_opps=opp_by_pid.get(pid),
            ai_assessment=ai_by_pid.get(pid),
            priors=priors,
        )
        ex = ex_by_pid.get(pid)
        is_conf = False
        expert_medal = None
        if ex and ex.get("payload"):
            pl = ex["payload"]
            if pl.get("expert_medal") or pl.get("is_staged_complete"):
                is_conf = True
                expert_medal = pl.get("expert_medal")

        # Second Pass model result - MEDAL SEMANTICS V2 authority gate.
        # A row is MODEL authority only when it is backed by a successful
        # current-semantics run. Legacy (run-less), stale and other-prompt rows
        # keep their DB rows but never drive BASE_MEDAL, EFFECTIVE_MEDAL,
        # the commercial category matrix or TOP opportunities.
        import json

        model_medal = None
        model_score = None
        model_reason = None
        cat_evals = []
        found_facts = []
        model_authority = "ABSENT"
        norm_res = ai.get("normalized_result") if ai else None
        if isinstance(norm_res, str):
            try:
                norm_res = json.loads(norm_res)
            except Exception:
                norm_res = {}
        if ai and ai.get("proposed_level"):
            semantics_version = (
                norm_res.get("semantics_version") if isinstance(norm_res, dict) else None
            )
            if is_model_authority_current(
                inference_run_id=ai.get("inference_run_id"),
                run_kind=ai.get("run_kind"),
                run_status=ai.get("run_status"),
                prompt_version=ai.get("prompt_version"),
                model_name=ai.get("model_name")
                or (norm_res.get("model_name") if isinstance(norm_res, dict) else None),
                semantics_version=semantics_version,
                is_stale=ai.get("is_stale"),
            ):
                model_authority = "CURRENT"
                raw_lvl = str(ai.get("proposed_level")).upper().strip()
                if raw_lvl in ("GOLD", "SILVER", "BRONZE", "WOOD"):
                    model_medal = raw_lvl
                if ai.get("confidence") is not None:
                    try:
                        model_score = int(float(ai["confidence"]) * 100)
                    except Exception:
                        pass
                model_reason = ai.get("reasons") or ""
                if isinstance(norm_res, dict):
                    cat_evals = norm_res.get("category_evaluations") or []
                    found_facts = norm_res.get("found_facts") or []
            else:
                model_authority = "LEGACY"

        is_expired = (
            p.get("award_status") == "submission_closed_waiting_award"
            or (p.get("end_date") is not None and str(p["end_date"])[:10] < today_str)
        )
        if is_expired:
            tier = 4
        elif is_conf:
            tier = 1
        elif model_medal:
            tier = 2
        elif res.canonical_preliminary_medal != "UNASSESSED":
            tier = 2
        else:
            tier = 3

        contour = resolve_source_contour(p.get("source_table"))
        law = contour.get("law_code", "UNKNOWN")

        p.update({
            "tier": tier,
            "is_confirmed": is_conf,
            "expert_medal": expert_medal,
            "model_medal": model_medal,
            "model_medal_authority": model_authority,
            "model_score": model_score,
            "model_reason": model_reason,
            "category_evaluations": cat_evals,
            "found_facts": found_facts,
            "preliminary_medal": res.canonical_preliminary_medal,
            "preliminary_source": res.canonical_preliminary_source,
            "priority_score": res.priority_score,
            "object_family": res.object_family,
            "law": law,
            "is_expired": is_expired,
        })
        resolve_card_effective_medals(p)
        cards.append(p)

    def torgi_sort_key(c: Dict[str, Any]) -> Tuple[Any, ...]:
        # 1. Active / Non-expired first (False before True)
        is_exp = bool(c.get("is_expired", False))
        # 2. Effective medal rank: GOLD(1) -> SILVER(2) -> BRONZE(3) -> WOOD(4) -> UNASSESSED(5) -> CLOSED(6)
        eff_rank = int(c.get("effective_medal_rank") or 5)
        # 3. Expert confirmed tie-breaker (True before False -> not is_conf)
        not_conf = not bool(c.get("is_confirmed", False))
        # 4. Priority score DESC
        score = float(c.get("priority_score") or 0)
        # 5. Deadline ASC (soonest first, nulls last)
        end_d = str(c.get("end_date") or "9999-99-99")
        # 6. Initial price DESC
        price = float(c.get("initial_price") or 0)
        # 7. Procurement ID DESC
        cid = int(c.get("id") or 0)
        return (is_exp, eff_rank, not_conf, -score, end_d, -price, -cid)

    cards.sort(key=torgi_sort_key)
    return cards


def load_torgi_workset(
    limit: int = 25,
    offset: int = 0,
    filters: Optional[TorgiFilterParams] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Load paginated, prioritized torgi cards and total matching count."""
    filters = filters or TorgiFilterParams()
    all_cards = get_evaluated_torgi_workset(hide_expired=filters.hide_expired)

    filtered: List[Dict[str, Any]] = []
    for c in all_cards:
        if filters.allowed_ids is not None and c["id"] not in filters.allowed_ids:
            continue
        if filters.effective_medal and filters.effective_medal != "Все":
            if c.get("effective_medal") != filters.effective_medal:
                continue
        if filters.model_medal and filters.model_medal != "Все":
            c_m = c.get("model_medal") or "UNASSESSED"
            if c_m != filters.model_medal:
                continue
        if filters.preliminary_medal and filters.preliminary_medal != "Все":
            if c["preliminary_medal"] != filters.preliminary_medal:
                continue
        if filters.expert_status and filters.expert_status != "Все":
            if filters.expert_status == "Подтверждено" and not c["is_confirmed"]:
                continue
            if filters.expert_status == "Не проверено" and c["is_confirmed"]:
                continue
        if filters.expert_medal and filters.expert_medal != "Все":
            if c["expert_medal"] != filters.expert_medal:
                continue
        if filters.object_family and filters.object_family != "Все":
            if c["object_family"] != filters.object_family:
                continue
        if filters.law and filters.law != "ALL":
            if filters.law in ("44", "44-FZ") and c["law"] != "44-FZ":
                continue
            if filters.law in ("223", "223-FZ") and c["law"] != "223-FZ":
                continue
            if filters.law in ("615", "615-PP") and c["law"] != "615-PP":
                continue
        if filters.region and filters.region != "Все":
            if c.get("delivery_region") != filters.region:
                continue
        if filters.search_query and filters.search_query.strip():
            sq = filters.search_query.strip().lower()
            name = str(c.get("auction_name") or "").lower()
            num = str(c.get("contract_number") or "").lower()
            if sq not in name and sq not in num:
                continue

        filtered.append(c)

    total_count = len(filtered)
    page_cards = filtered[offset : offset + limit]
    return page_cards, total_count
