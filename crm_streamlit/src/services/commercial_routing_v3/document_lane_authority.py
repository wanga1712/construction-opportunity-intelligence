"""Document-queue lane authority.

discovery_required means DOCUMENT_RESEARCH_REQUIRED (verify/refine Candidate).
It is not HUMAN_REVIEW_REQUIRED and must not force discovery_review when a
current GOLD/SILVER hypothesis already exists.

Queue mapping only. Does not change Candidate routing semantics.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

DOCUMENT_RESEARCH_ACTIONS = frozenset(
    {"LIGHT_RESEARCH", "PRIORITY_DOCS", "DEEP_RESEARCH"}
)
ACTIONABLE_MEDALS = frozenset({"GOLD", "SILVER"})
NON_EXECUTABLE_STATES = frozenset(
    {
        "NO_COMMERCIAL_ENTRY",
        "CLOSED",
        "CLOSED_DIRECT_SUPPLY",
        "COMMERCIAL_WINDOW_CLOSED",
        "WAITING_SOURCE_OUTCOME",
        "SUPPRESSED",
    }
)


def _u(value: Any) -> str:
    return str(value or "").strip().upper()


def has_document_research_hypothesis(
    *,
    has_valid_category: bool,
    track: Optional[str],
    research_action: Optional[str],
    current_effective_medal: Optional[str] = None,
) -> bool:
    if not has_valid_category:
        return False
    if _u(track) in ("", "UNKNOWN", "NO_COMMERCIAL_ENTRY"):
        return False
    if _u(research_action) not in DOCUMENT_RESEARCH_ACTIONS:
        return False
    if _u(current_effective_medal) == "WOOD":
        return False
    return True


def is_human_review_required(
    *,
    review_required: bool = False,
    discovery_required: bool = False,
    has_valid_category: bool = False,
    track: Optional[str] = None,
    research_action: Optional[str] = None,
    current_effective_medal: Optional[str] = None,
    commercial_state: Optional[str] = None,
) -> bool:
    """True only for actual non-actionable review — not document research."""
    if has_document_research_hypothesis(
        has_valid_category=has_valid_category,
        track=track,
        research_action=research_action,
        current_effective_medal=current_effective_medal,
    ):
        return False
    if _u(commercial_state) in NON_EXECUTABLE_STATES:
        return False
    if _u(commercial_state) == "REVIEW_REQUIRED":
        return True
    if review_required:
        return True
    if not has_valid_category and _u(track) in ("", "UNKNOWN"):
        return True
    if discovery_required and not has_valid_category:
        return True
    return False


def apply_current_opportunity_authority(
    decision: Dict[str, Any],
    current_opportunities: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Overlay CURRENT opportunity rows over stale assessment flags."""
    out = dict(decision)
    ranked: List[Dict[str, Any]] = []
    for row in current_opportunities or []:
        medal = _u(row.get("current_effective_medal") or row.get("candidate_medal"))
        action = _u(row.get("research_action"))
        track = row.get("opportunity_track")
        state = _u(row.get("commercial_state"))
        if state in NON_EXECUTABLE_STATES:
            continue
        if medal not in ACTIONABLE_MEDALS:
            continue
        if action not in DOCUMENT_RESEARCH_ACTIONS:
            continue
        if _u(track) in ("", "UNKNOWN", "NO_COMMERCIAL_ENTRY"):
            continue
        ranked.append({**row, "_medal": medal, "_action": action})
    ranked.sort(
        key=lambda r: (0 if r["_medal"] == "GOLD" else 1, r.get("commercial_priority_score") or 0),
        reverse=False,
    )
    if not ranked:
        out["document_research_required"] = False
        out["human_review_required"] = is_human_review_required(
            review_required=bool(out.get("review_required")),
            discovery_required=bool(out.get("discovery_required")),
            has_valid_category=bool(out.get("trigger_opportunities")),
            track=out.get("opportunity_track"),
            research_action=out.get("research_action"),
            current_effective_medal=out.get("candidate_medal"),
            commercial_state=out.get("commercial_state"),
        )
        return out

    best = ranked[0]
    medal = best["_medal"]
    hyps = []
    for row in ranked:
        hyps.append(
            {
                "category_code": row.get("commercial_category_code") or row.get("category_code"),
                "subcategory_code": row.get("subcategory_code"),
                "opportunity_track": row.get("opportunity_track"),
                "candidate_medal": row.get("_medal"),
                "research_action": row.get("research_action"),
                "commercial_state": row.get("commercial_state"),
            }
        )
    out["trigger_opportunities"] = hyps
    out["opportunity_associations"] = hyps
    out["candidate_medal"] = medal
    out["opportunity_track"] = best.get("opportunity_track")
    out["research_action"] = best.get("research_action")
    out["primary_category"] = best.get("commercial_category_code") or best.get("category_code")
    out["commercial_state"] = best.get("commercial_state")
    # Stale assessment discovery/review flags do not override current actionability.
    out["discovery_required"] = False
    out["review_required"] = False
    out["document_research_required"] = True
    out["human_review_required"] = False
    return out
