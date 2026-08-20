"""Единый контракт эффективной AI-оценки закупки.

Состояния ai_status:
  UNASSESSED  — нет ни одной записи в procurement_ai_assessments
  ASSESSED    — есть is_current=True запись с валидным normalized_result
  INCOMPLETE  — есть is_current=True запись, но normalized_result=NULL или не проходит schema
  FAILED      — последний статус assessment = ERROR/FAILED
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

_LEVEL_RANKS: dict[Optional[str], int] = {
    "GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1, None: 0
}

# Sorting group ranks for list ordering (higher = shown first)
SORT_GROUP_RANK: dict[str, int] = {
    "GOLD":        80_000,
    "SILVER":      60_000,
    "BRONZE":      40_000,
    "WOOD":        20_000,
    "UNASSESSED":   5_000,
    "INCOMPLETE":   3_000,
    "FAILED":       1_000,
    "OUT_OF_PROFILE":   0,
}


def _validate_normalized_result(nr: dict) -> bool:
    """Minimal schema validation for normalized_result."""
    if not isinstance(nr, dict):
        return False
    # Must have at minimum business_scope_status or category_opportunities key
    return (
        "business_scope_status" in nr
        or "category_opportunities" in nr
        or "candidate_level" in nr
    )


@dataclass
class EffectiveAssessment:
    procurement_id: int

    # AI pipeline state
    ai_status: str = "UNASSESSED"       # UNASSESSED | ASSESSED | INCOMPLETE | FAILED
    has_manual_override: bool = False
    assessment_version: Optional[int] = None
    model_version: Optional[str] = None

    # Classification
    route_profile: Optional[str] = None
    object_type: Optional[str] = None
    procurement_type: Optional[str] = None
    confidence: Optional[float] = None
    reasons: Optional[str] = None

    # Business scope
    business_relevance: str = "UNKNOWN"     # UNKNOWN | IN_PROFILE | OUT_OF_PROFILE | HIGH | MEDIUM | LOW

    # Best opportunity (procurement-level)
    best_opportunity_category: Optional[str] = None
    best_candidate_level: Optional[str] = None     # None | GOLD | SILVER | BRONZE | WOOD
    best_candidate_score: Optional[float] = None
    overall_research_action: Optional[str] = None

    # All opportunities
    category_opportunities: list[dict] = field(default_factory=list)

    # Sort group derived from state + best level
    sort_group: str = "UNASSESSED"

    def sort_key(self, time_score: int = 0, price_bonus: int = 0) -> tuple:
        """Explicit rank tuple for sorting. Higher = first."""
        group_rank = SORT_GROUP_RANK.get(self.sort_group, 0)
        score = self.best_candidate_score or 0.0
        return (group_rank, score, time_score, price_bonus)


def _compute_effective_assessment(
    procurement_id: int,
    ai_row: Optional[dict],
    override_row: Optional[dict],
    cat_overrides: list[dict],
) -> EffectiveAssessment:
    """Apply AI result + manual overrides → EffectiveAssessment."""
    ea = EffectiveAssessment(procurement_id=procurement_id)

    # ── Determine AI status ────────────────────────────────────────────────
    if ai_row is None:
        ea.ai_status = "UNASSESSED"
        ea.sort_group = "UNASSESSED"
        return ea

    raw_status = (ai_row.get("status") or "").upper()
    if raw_status in ("ERROR", "FAILED"):
        ea.ai_status = "FAILED"
        ea.sort_group = "FAILED"
        log.warning("procurement_id=%s AI status=FAILED", procurement_id)
        return ea

    nr_raw = ai_row.get("normalized_result")
    if not nr_raw:
        ea.ai_status = "INCOMPLETE"
        ea.sort_group = "INCOMPLETE"
        log.warning(
            "pipeline_integrity: procurement_id=%s status=%s but normalized_result IS NULL",
            procurement_id, raw_status
        )
        return ea

    try:
        nr = json.loads(nr_raw) if isinstance(nr_raw, str) else (nr_raw or {})
    except Exception:
        ea.ai_status = "INCOMPLETE"
        ea.sort_group = "INCOMPLETE"
        log.warning(
            "pipeline_integrity: procurement_id=%s normalized_result JSON parse error",
            procurement_id
        )
        return ea

    if not _validate_normalized_result(nr):
        ea.ai_status = "INCOMPLETE"
        ea.sort_group = "INCOMPLETE"
        log.warning(
            "pipeline_integrity: procurement_id=%s normalized_result failed schema validation: %s",
            procurement_id, list(nr.keys())
        )
        return ea

    # ── AI is ASSESSED — fill AI fields ───────────────────────────────────
    ea.ai_status = "ASSESSED"
    ea.assessment_version = ai_row.get("assessment_version")
    ea.model_version       = ai_row.get("model_version")
    ea.route_profile       = ai_row.get("proposed_route_profile")
    ea.object_type         = ai_row.get("proposed_object_type")
    ea.procurement_type    = ai_row.get("proposed_procurement_type")
    ea.confidence          = ai_row.get("confidence")
    ea.reasons             = ai_row.get("reasons")

    # scope — fail closed: missing/invalid never become IN_PROFILE
    from src.services.business_scope import canonicalize_business_scope

    ea.business_relevance = canonicalize_business_scope(nr.get("business_scope_status"))

    # AI opportunities (baseline)
    ai_opps: list[dict] = nr.get("category_opportunities") or []
    ai_cand_level: Optional[str] = nr.get("candidate_level")   # no fallback to WOOD
    ai_cand_score: Optional[float] = nr.get("candidate_score")

    # ── Apply manual overrides ────────────────────────────────────────────
    ea.has_manual_override = bool(override_row or cat_overrides)

    if override_row:
        man_rel = override_row.get("business_relevance")
        if man_rel:
            ea.business_relevance = man_rel
        ea.overall_research_action = override_row.get("overall_research_action")

    cat_map: dict[str, dict] = {co["category_code"]: co for co in cat_overrides}
    eff_opps: list[dict] = []

    if cat_map:
        for cat_code, co in cat_map.items():
            if (co.get("opportunity_status") or "") != "ABSENT":
                eff_opps.append({
                    "category_code":          cat_code,
                    "subcategory_code":       co.get("subcategory_code"),
                    "opportunity_status":     co.get("opportunity_status"),
                    "expected_role":          co.get("expected_role"),
                    "commercial_entry_point": co.get("commercial_entry_point"),
                    "expected_volume":        co.get("expected_volume"),
                    "confidence":             1.0,
                    "priority":               float(co.get("priority") or 0.0),
                    "research_action":        co.get("research_action"),
                    "candidate_level":        co.get("manual_candidate_level"),
                    "candidate_score":        None,
                    "manual_override":        True,
                    "manual_reason":          co.get("manual_reason"),
                })
        # append AI opps not overridden
        for opp in ai_opps:
            if opp.get("category_code") not in cat_map:
                eff_opps.append(opp)
    else:
        eff_opps = list(ai_opps)

    ea.category_opportunities = eff_opps

    # ── Compute best level/score from effective opportunities ─────────────
    if cat_map:
        best_level: Optional[str] = None
        best_score: Optional[float] = None
        best_cat: Optional[str] = None
        for opp in eff_opps:
            lvl = opp.get("candidate_level")
            scr = opp.get("candidate_score") or 0.0
            if _LEVEL_RANKS.get(lvl, 0) > _LEVEL_RANKS.get(best_level, 0):
                best_level, best_score, best_cat = lvl, scr, opp.get("category_code")
            elif _LEVEL_RANKS.get(lvl, 0) == _LEVEL_RANKS.get(best_level, 0) and best_level:
                if scr > (best_score or 0.0):
                    best_score = scr
        ea.best_candidate_level = best_level
        ea.best_candidate_score = best_score
        ea.best_opportunity_category = best_cat
    else:
        ea.best_candidate_level  = ai_cand_level
        ea.best_candidate_score  = ai_cand_score
        ea.best_opportunity_category = (
            eff_opps[0].get("category_code") if eff_opps else None
        )

    if not ea.overall_research_action and eff_opps:
        actions = [o.get("research_action") for o in eff_opps if o.get("research_action")]
        ea.overall_research_action = actions[0] if actions else None

    # ── OUT_OF_PROFILE → clear medal/score ───────────────────────────────
    if ea.business_relevance == "OUT_OF_PROFILE":
        ea.best_candidate_level = None
        ea.best_candidate_score = None
        ea.sort_group = "OUT_OF_PROFILE"
    else:
        ea.sort_group = ea.best_candidate_level or "WOOD"

    return ea


def get_effective_business_assessments(
    procurement_ids: list[int],
    crm_db,
) -> dict[int, EffectiveAssessment]:
    """Bulk load effective assessments for a list of procurement IDs.

    Returns dict[procurement_id → EffectiveAssessment].
    Single query per table — no N+1.
    """
    if not procurement_ids:
        return {}

    ids_tuple = tuple(set(procurement_ids))

    # ── 1. Current AI assessments (bulk) ──────────────────────────────────
    ai_rows: dict[int, dict] = {}
    try:
        rows = crm_db.execute_query(
            """
            SELECT procurement_id, assessment_version, status, model_version,
                   proposed_route_profile, proposed_object_type, proposed_procurement_type,
                   confidence, reasons, normalized_result
            FROM procurement_ai_assessments
            WHERE is_current = TRUE
              AND procurement_id = ANY(%s)
            """,
            (list(ids_tuple),)
        )
        for r in (rows or []):
            ai_rows[r["procurement_id"]] = dict(r)
    except Exception as e:
        log.error("get_effective_business_assessments: AI query failed: %s", e)

    # ── 2. Manual overrides (bulk) ─────────────────────────────────────────
    override_rows: dict[int, dict] = {}
    try:
        rows = crm_db.execute_query(
            """
            SELECT procurement_id, business_relevance, overall_research_action
            FROM crm_manual_overrides
            WHERE procurement_id = ANY(%s)
            """,
            (list(ids_tuple),)
        )
        for r in (rows or []):
            override_rows[r["procurement_id"]] = dict(r)
    except Exception as e:
        log.error("get_effective_business_assessments: override query failed: %s", e)

    # ── 3. Category overrides (bulk) ───────────────────────────────────────
    cat_override_rows: dict[int, list[dict]] = {pid: [] for pid in ids_tuple}
    try:
        rows = crm_db.execute_query(
            """
            SELECT procurement_id, category_code, subcategory_code, opportunity_status,
                   expected_role, commercial_entry_point, expected_volume, priority,
                   research_action, manual_candidate_level, manual_reason
            FROM crm_manual_category_overrides
            WHERE procurement_id = ANY(%s)
            """,
            (list(ids_tuple),)
        )
        for r in (rows or []):
            cat_override_rows.setdefault(r["procurement_id"], []).append(dict(r))
    except Exception as e:
        log.error("get_effective_business_assessments: cat_override query failed: %s", e)

    # ── 4. Compute ─────────────────────────────────────────────────────────
    result: dict[int, EffectiveAssessment] = {}
    for pid in procurement_ids:
        result[pid] = _compute_effective_assessment(
            procurement_id=pid,
            ai_row=ai_rows.get(pid),
            override_row=override_rows.get(pid),
            cat_overrides=cat_override_rows.get(pid, []),
        )
    return result

