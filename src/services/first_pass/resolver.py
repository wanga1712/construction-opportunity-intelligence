"""Pure resolution logic for First Pass metadata scoring and projection."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.services.medal_semantics_v2 import (
    canonical_category,
    evaluate_metadata_categories,
    relevance_to_medal,
    strongest_category_medal,
)
from src.services.expert_object_taxonomy import (
    COMMERCIAL,
    INDUSTRIAL,
    INFRASTRUCTURE,
    OBJECT_SECTOR_FIELD,
    OBJECT_TYPE_FIELD,
    RESIDENTIAL,
    SOCIAL,
    URBAN_IMPROVEMENT,
    normalize_object_axes,
    types_of_sector,
)

# Sectors whose objects belong to the commercial (non-social) family for
# First Pass routing. Derived from the single canonical object taxonomy.
_COMMERCIAL_FAMILY_SECTORS = frozenset(
    {COMMERCIAL, RESIDENTIAL, INDUSTRIAL, INFRASTRUCTURE, URBAN_IMPROVEMENT}
)
_COMMERCIAL_FAMILY_TYPES = frozenset(
    t for _s in _COMMERCIAL_FAMILY_SECTORS for t in types_of_sector(_s)
)
_SOCIAL_TYPES = frozenset(t for t in types_of_sector(SOCIAL))

MEDAL_BASE_SCORES: Dict[str, int] = {
    "GOLD": 70,
    "SILVER": 50,
    "BRONZE": 30,
    "WOOD": 10,
    "UNASSESSED": 20,
}

MEDAL_RANKS: Dict[str, int] = {
    "GOLD": 4,
    "SILVER": 3,
    "BRONZE": 2,
    "WOOD": 1,
    "UNASSESSED": 0,
}


def normalize_medal_name(medal: Optional[str]) -> str:
    if not medal:
        return "UNASSESSED"
    m = str(medal).strip().upper()
    return m if m in ("GOLD", "SILVER", "BRONZE", "WOOD") else "UNASSESSED"


def normalize_to_100(val: Optional[float]) -> Tuple[float, Optional[float]]:
    """Normalize raw confidence/score (whether 0..1 or 0..100) to a clean 0..100 scale."""
    if val is None:
        return 0.0, None
    try:
        f = float(val)
    except (ValueError, TypeError):
        return 0.0, None

    raw_val = f
    # If in 0..1 range (excluding exactly 0 and > 1.0)
    if 0.0 < f <= 1.0:
        norm = f * 100.0
    else:
        norm = max(0.0, min(100.0, f))
    return round(norm, 2), raw_val


def select_best_eligible_category_opportunity(
    opps: Sequence[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], int]:
    """Deterministically select the strongest eligible category opportunity.

    Rules:
      - Exclude NO_COMMERCIAL_ENTRY / explicitly excluded / REJECTED / ABSENT
      - Medal rank: GOLD > SILVER > BRONZE > WOOD
      - Tie-break by highest normalized composite/candidate score
      - Secondary tie-break by ID DESC
    """
    if not opps:
        return None, 0

    total_count = len(opps)
    eligible: List[Dict[str, Any]] = []

    for opp in opps:
        # Check exclusion flags
        state = str(opp.get("commercial_state") or "").upper()
        if state in ("REJECTED", "ABSENT", "EXCLUDED"):
            continue

        status = str(opp.get("opportunity_status") or "").upper()
        if status in ("REJECTED", "ABSENT", "EXCLUDED"):
            continue

        track = str(opp.get("opportunity_track") or opp.get("commercial_entry_point") or "").upper()
        if track in ("NO_COMMERCIAL_ENTRY", "NONE", "ABSENT"):
            continue

        medal = normalize_medal_name(
            opp.get("candidate_medal")
            or opp.get("current_effective_medal")
            or opp.get("confirmed_base_medal")
        )
        if medal == "UNASSESSED":
            continue

        raw_score = opp.get("candidate_score") or opp.get("composite_score") or opp.get("confidence")
        norm_score, _ = normalize_to_100(raw_score)

        opp_id = int(opp.get("id") or 0)
        eligible.append({
            "opp": opp,
            "medal": medal,
            "rank": MEDAL_RANKS.get(medal, 0),
            "norm_score": norm_score,
            "raw_score": raw_score,
            "id": opp_id,
        })

    if not eligible:
        return None, total_count

    # Sort by medal rank DESC -> score DESC -> ID DESC
    eligible.sort(key=lambda x: (x["rank"], x["norm_score"], x["id"]), reverse=True)
    return eligible[0]["opp"], total_count


def resolve_object_family(
    scope_type: Optional[str] = None,
    sector: Optional[str] = None,
    object_type: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Normalize object family to one of SOCIAL, COMMERCIAL, DIRECT_SUPPLY, OTHER.

    Uses existing normalized taxonomy/object_type first.
    Title/keyword regex matching is fallback only when authoritative taxonomy result is absent.
    """
    # Canonicalize first: legacy sector names / Russian free text / model echoes
    # all resolve through the single object taxonomy source.
    axes = normalize_object_axes(sector=sector, object_type=object_type)
    sec = axes[OBJECT_SECTOR_FIELD]
    obj = axes[OBJECT_TYPE_FIELD] or str(object_type or "").strip().upper()

    # 1. Authoritative SOCIAL taxonomy
    if sec == SOCIAL or obj in _SOCIAL_TYPES:
        return "SOCIAL"

    # 2. Authoritative COMMERCIAL / Residential / Industrial / Infrastructure /
    #    Urban-improvement taxonomy
    if sec in _COMMERCIAL_FAMILY_SECTORS or obj in _COMMERCIAL_FAMILY_TYPES:
        return "COMMERCIAL"

    # 3. Fallback: Text/keyword matching when authoritative taxonomy is absent
    text_fallback = (str(object_type or "") + " " + str(title or "")).lower()
    if any(k in text_fallback for k in ("школ", "детск", "сад", "больниц", "поликлиник", "спорт", "культур", "социальн")):
        return "SOCIAL"
    if any(k in text_fallback for k in ("жил", "мкд", "офис", "торгов", "склад", "производств", "завод", "гостиниц", "отел", "промышленн", "дорог", "мост", "инфраструктур")):
        return "COMMERCIAL"

    # 4. Scope classification
    st = str(scope_type or "").strip().upper()
    if st in ("DIRECT_GOODS", "DIRECT_SUPPLY"):
        return "DIRECT_SUPPLY"

    return "OTHER"


def resolve_canonical_preliminary_medal(
    category_opps: Optional[Sequence[Dict[str, Any]]] = None,
    ai_assessment: Optional[Dict[str, Any]] = None,
    okpd_target_classification: str = "UNKNOWN_OKPD",
    matched_priors: Optional[List[Dict[str, Any]]] = None,
    *,
    title: Optional[str] = None,
    scope_text: Optional[str] = None,
    okpd_code: Optional[str] = None,
) -> Tuple[str, float, Optional[float], str, Optional[str], Optional[str], int, Optional[int]]:
    """Resolve the PRELIMINARY medal from metadata-stage category semantics only.

    MEDAL SEMANTICS V2 (ANALYTICS-V2-MEDAL-SEMANTICS-V2-REBUILD-1):

      * Only metadata-stage signals participate. Second Pass output
        (``procurement_ai_assessments.proposed_level`` / ``normalized_result``)
        is NOT metadata and is deliberately ignored here; ``ai_assessment`` is
        accepted for signature compatibility only.
      * A medal above UNASSESSED requires a canonical commercial category
        (``crm_product_categories``); PRELIMINARY GOLD/SILVER/WOOD without a
        canonical category is forbidden.
      * A bare OKPD prior never yields a medal. OKPD priors only nominate
        candidate categories (routing, download priority, research priority).
      * ``initial_price`` is not an input: price can never create relevance.

    Returns (medal, normalized_score, raw_confidence, source, category,
    subcategory, total_opportunities, selected_opportunity_id).
    """
    del ai_assessment  # MEDAL SEMANTICS V2: model output is not a First Pass signal.

    # 1. Category nomination (identity only — never strength).
    total_opps = 0
    best_opp: Optional[Dict[str, Any]] = None
    candidate_categories: List[str] = []
    if category_opps:
        best_opp, total_opps = select_best_eligible_category_opportunity(category_opps)
        for opp in category_opps:
            cat = canonical_category(opp.get("commercial_category_code") or opp.get("category_id"))
            if cat and cat not in candidate_categories:
                candidate_categories.append(cat)
    if matched_priors:
        for prior in matched_priors:
            cat = canonical_category(prior.get("commercial_category_code"))
            if cat and cat not in candidate_categories:
                candidate_categories.append(cat)

    # 2. Metadata-stage semantic scoring of canonical categories.
    metadata_text = " ".join(str(x) for x in (title, scope_text) if x)
    evaluations = evaluate_metadata_categories(
        metadata_text,
        candidate_categories=candidate_categories or None,
    )
    medal = strongest_category_medal(evaluations)
    if medal is None:
        return "UNASSESSED", 0.0, None, "UNASSESSED", None, None, total_opps, None

    winner = next(
        (e for e in evaluations if relevance_to_medal(e.get("relevance_level")) == medal),
        evaluations[0] if evaluations else None,
    )
    cat = winner.get("category_code") if winner else None
    subcat = None
    opp_id = None
    if best_opp and canonical_category(best_opp.get("commercial_category_code")) == cat:
        subcat = best_opp.get("commercial_subcategory_code") or best_opp.get("subcategory_code")
        opp_id = int(best_opp.get("id")) if best_opp.get("id") is not None else None

    matched_signals = len((winner or {}).get("positive_signals") or [])
    confidence = min(1.0, round(0.5 + 0.15 * matched_signals, 2))
    return (
        medal,
        float(MEDAL_BASE_SCORES.get(medal, 20)),
        confidence,
        "METADATA_CATEGORY_SEMANTIC",
        cat,
        subcat,
        total_opps,
        opp_id,
    )

def resolve_download_decision(
    okpd_target_classification: str,
    canonical_preliminary_medal: str,
    doc_count: int,
) -> str:
    """Derive download decision: DOWNLOAD_REQUIRED, DOWNLOAD_DEFER, DOWNLOAD_SKIP, NO_LINKS."""
    if okpd_target_classification == "OUT_OF_TARGET":
        return "DOWNLOAD_SKIP"

    if doc_count <= 0:
        return "NO_LINKS"

    medal = normalize_medal_name(canonical_preliminary_medal)

    if medal in ("GOLD", "SILVER", "BRONZE"):
        return "DOWNLOAD_REQUIRED"

    if medal == "WOOD":
        return "DOWNLOAD_DEFER"

    # UNASSESSED
    return "DOWNLOAD_DEFER"


def calculate_deadline_metrics(
    submission_end_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> Tuple[int, Optional[float]]:
    """Calculate (urgency_bonus, days_to_deadline)."""
    if submission_end_at is None:
        return 0, None

    if now is None:
        now = datetime.now(timezone.utc)

    if submission_end_at.tzinfo is None:
        submission_end_at = submission_end_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta_seconds = (submission_end_at - now).total_seconds()
    days = round(delta_seconds / 86400.0, 2)

    if delta_seconds < 0:
        return 0, days  # Expired

    if days <= 1.0:
        return 20, days
    if days <= 3.0:
        return 15, days
    if days <= 7.0:
        return 10, days
    if days <= 14.0:
        return 5, days
    return 0, days


def calculate_priority_score(
    canonical_preliminary_medal: str,
    submission_end_at: Optional[datetime] = None,
    is_explicit_target_profile: bool = False,
    now: Optional[datetime] = None,
) -> Tuple[int, int, int, int, Optional[float]]:
    """Compute (priority_score, medal_base, urgency_bonus, relevance_bonus, days_to_deadline).

    Direct supply alone does NOT give a relevance bonus (+0).
    Only independently proven relevance yields relevance_bonus = 10.
    Expired active procurements (days < 0) yield priority_score = 0.
    """
    medal = normalize_medal_name(canonical_preliminary_medal)
    base = MEDAL_BASE_SCORES.get(medal, 20)
    urgency_bonus, days = calculate_deadline_metrics(submission_end_at, now=now)
    relevance_bonus = 10 if is_explicit_target_profile else 0

    if days is not None and days < 0:
        # Expired active queue row receives priority_score = 0 and 0 bonuses
        return 0, base, 0, 0, days

    score = max(0, min(100, base + urgency_bonus + relevance_bonus))
    return score, base, urgency_bonus, relevance_bonus, days
