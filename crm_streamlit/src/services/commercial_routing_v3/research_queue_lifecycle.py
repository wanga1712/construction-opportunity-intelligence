"""V3 lifecycle-aware research queue admission — dry-run contract only.

No DB writes. No document downloads. Used for readiness audit and future producers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional, Sequence

from src.domain.commercial_opportunity_lifecycle import (
    CommercialOpportunityState,
    SourceLifecycleEvent,
)
from src.services.commercial_routing_v3.opportunity_lifecycle_sync import _compute_decision
from src.services.commercial_routing_v3.source_contour import resolve_source_contour
from src.services.commercial_routing_v3.document_lane_authority import (
    is_human_review_required,
)
from src.services.commercial_routing_v3.source_lifecycle import (
    normalize_source_lifecycle_from_procurement,
)

class ResearchPurpose(StrEnum):
    CONFIRM_DIRECT_SPECIFICATION = "CONFIRM_DIRECT_SPECIFICATION"
    FIND_EMBEDDED_MATERIAL = "FIND_EMBEDDED_MATERIAL"
    FIND_DESIGN_REQUIREMENT = "FIND_DESIGN_REQUIREMENT"
    DESIGN_INFLUENCE_RESEARCH = "DESIGN_INFLUENCE_RESEARCH"
    DISCOVER_COMMERCIAL_CATEGORY = "DISCOVER_COMMERCIAL_CATEGORY"
    POST_AWARD_FOLLOW_UP = "POST_AWARD_FOLLOW_UP"


class ResearchLane(StrEnum):
    OPEN_ACTIVE = "open_active"
    CRM_ACTIVE_HOT = "crm_active_hot"
    DISCOVERY_REVIEW = "discovery_review"
    AWARDED_FOLLOW_UP = "awarded_follow_up"
    HOLD = "hold"
    CLOSED_NO_RESEARCH = "closed_no_research"


# High-value filename/title tokens (metadata only; do not invent missing fields).
HIGH_VALUE_DOC_TOKENS = (
    "техническ",
    "техзадани",
    " тз",
    "тз ",
    "тз.",
    "описани",
    "объект",
    "проектн",
    "рабоч",
    "ведомост",
    "спецификац",
    "смет",
    "requirement",
    "design",
    "specification",
    "tz_",
    "_tz",
)

LOW_VALUE_DOC_TOKENS = (
    "протокол",
    "извещен",
    "выписк",
    "обеспечен",
    "банковск",
    "гарант",
    "заявк",
    "согласие",
    "фото",
    "презентац",
)


@dataclass(frozen=True)
class DryRunQueueDecision:
    queue_eligible: bool
    queue_state: str  # ELIGIBLE | HOLD | CLOSED_NO_RESEARCH | NOT_ROUTED | INELIGIBLE
    research_lane: Optional[str]
    research_purpose: Optional[str]
    research_priority: int
    commercial_lifecycle_state: Optional[str]
    source_lifecycle_event: str
    reason: str
    is_active_commercial_lead: bool
    fake_category_allowed: bool = False
    fake_medal_allowed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def links_table_for_source(source_table: str) -> str:
    if "223" in (source_table or ""):
        return "links_documentation_223_fz"
    return "links_documentation_44_fz"


def purpose_for_track(
    track: Optional[str],
    *,
    discovery_review: bool,
    source_event: SourceLifecycleEvent,
) -> ResearchPurpose:
    if discovery_review:
        return ResearchPurpose.DISCOVER_COMMERCIAL_CATEGORY
    t = (track or "").upper()
    if source_event == SourceLifecycleEvent.AWARDED and t in (
        "EMBEDDED_MATERIAL",
        "DESIGN_REQUIREMENT",
        "DESIGN_INFLUENCE",
    ):
        return ResearchPurpose.POST_AWARD_FOLLOW_UP
    if t == "DIRECT_SUPPLY":
        return ResearchPurpose.CONFIRM_DIRECT_SPECIFICATION
    if t == "EMBEDDED_MATERIAL":
        return ResearchPurpose.FIND_EMBEDDED_MATERIAL
    if t == "DESIGN_REQUIREMENT":
        return ResearchPurpose.FIND_DESIGN_REQUIREMENT
    if t == "DESIGN_INFLUENCE":
        return ResearchPurpose.DESIGN_INFLUENCE_RESEARCH
    return ResearchPurpose.DISCOVER_COMMERCIAL_CATEGORY


def document_research_required_for_commercial_entry(
    *,
    opportunity_track: Optional[str],
    source_event: SourceLifecycleEvent,
    procurement_form: Optional[str] = None,
) -> bool:
    """AWARDED DIRECT_SUPPLY never starts commercial-entry document research."""
    track = (opportunity_track or "").upper()
    if source_event == SourceLifecycleEvent.AWARDED and track == "DIRECT_SUPPLY":
        return False
    if (
        source_event == SourceLifecycleEvent.AWARDED
        and str(procurement_form or "").upper() == "DIRECT_GOODS_PURCHASE"
        and track in ("DIRECT_SUPPLY", "")
    ):
        return False
    return True


def classify_doc_value(file_name: Optional[str]) -> str:
    """Return HIGH | LOW | UNKNOWN from available filename metadata only."""
    name = (file_name or "").lower()
    if not name:
        return "UNKNOWN"
    if any(tok in name for tok in HIGH_VALUE_DOC_TOKENS):
        return "HIGH"
    if any(tok in name for tok in LOW_VALUE_DOC_TOKENS):
        return "LOW"
    return "UNKNOWN"


def select_docs_for_research(
    links: Sequence[Dict[str, Any]],
    *,
    max_high: int = 12,
    max_unknown: int = 6,
    include_low: bool = False,
) -> Dict[str, Any]:
    """Plan selection from link metadata; does not download."""
    buckets = {"HIGH": [], "UNKNOWN": [], "LOW": []}
    for row in links:
        grade = classify_doc_value(row.get("file_name"))
        buckets[grade].append(row)
    selected = list(buckets["HIGH"][:max_high])
    if len(selected) < max_high:
        need = max_unknown
        selected.extend(buckets["UNKNOWN"][:need])
    if include_low:
        selected.extend(buckets["LOW"][:3])
    return {
        "selected_count": len(selected),
        "high_count": len(buckets["HIGH"]),
        "unknown_count": len(buckets["UNKNOWN"]),
        "low_count": len(buckets["LOW"]),
        "selected": selected,
        "deferred_low": buckets["LOW"] if not include_low else [],
    }


def dry_run_research_admission(
    *,
    procurement: Dict[str, Any],
    opportunity_track: Optional[str] = None,
    discovery_required: bool = False,
    review_required: bool = False,
    has_valid_category: bool = False,
    routed: bool = False,
    research_action: Optional[str] = None,
    current_effective_medal: Optional[str] = None,
    commercial_state: Optional[str] = None,
) -> DryRunQueueDecision:
    """Lifecycle + track admission. Projected-but-unrouted rows are NOT eligible.

    discovery_required is DOCUMENT_RESEARCH_REQUIRED, not HUMAN_REVIEW_REQUIRED.
    A current GOLD/SILVER hypothesis with a research action stays on the
    production document lane even if a stale assessment flag is set.
    """
    source_event = normalize_source_lifecycle_from_procurement(procurement)
    track = (opportunity_track or "").strip().upper() or None

    if not routed:
        return DryRunQueueDecision(
            queue_eligible=False,
            queue_state="NOT_ROUTED",
            research_lane=None,
            research_purpose=None,
            research_priority=0,
            commercial_lifecycle_state=None,
            source_lifecycle_event=source_event.value,
            reason="PROJECTED_PENDING_ROUTING",
            is_active_commercial_lead=False,
        )

    if track == "NO_COMMERCIAL_ENTRY":
        return DryRunQueueDecision(
            queue_eligible=False,
            queue_state="CLOSED_NO_RESEARCH",
            research_lane=ResearchLane.CLOSED_NO_RESEARCH.value,
            research_purpose=None,
            research_priority=0,
            commercial_lifecycle_state=CommercialOpportunityState.SUPPRESSED.value,
            source_lifecycle_event=source_event.value,
            reason="NO_COMMERCIAL_ENTRY",
            is_active_commercial_lead=False,
        )

    medal_u = str(current_effective_medal or "").strip().upper()
    if medal_u == "WOOD":
        return DryRunQueueDecision(
            queue_eligible=False,
            queue_state="INELIGIBLE",
            research_lane=None,
            research_purpose=None,
            research_priority=0,
            commercial_lifecycle_state=commercial_state,
            source_lifecycle_event=source_event.value,
            reason="WOOD_NOT_AUTO_EXECUTABLE",
            is_active_commercial_lead=False,
        )

    discovery_review = is_human_review_required(
        review_required=review_required,
        discovery_required=discovery_required,
        has_valid_category=has_valid_category,
        track=track,
        research_action=research_action,
        current_effective_medal=current_effective_medal,
        commercial_state=commercial_state,
    )

    if discovery_review and source_event in (
        SourceLifecycleEvent.OPEN,
        SourceLifecycleEvent.WAITING_SOURCE_OUTCOME,
        SourceLifecycleEvent.AWARDED,
    ):
        # WAITING: hold active sales, but discovery lane may still inspect docs later;
        # default HOLD for WAITING unless explicitly discovery_required.
        if source_event == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME and not discovery_required:
            return DryRunQueueDecision(
                queue_eligible=False,
                queue_state="HOLD",
                research_lane=ResearchLane.HOLD.value,
                research_purpose=purpose_for_track(
                    track, discovery_review=True, source_event=source_event
                ).value,
                research_priority=0,
                commercial_lifecycle_state=CommercialOpportunityState.WAITING_SOURCE_OUTCOME.value,
                source_lifecycle_event=source_event.value,
                reason="WAITING_SOURCE_OUTCOME_HOLD",
                is_active_commercial_lead=False,
            )
        purpose = purpose_for_track(track, discovery_review=True, source_event=source_event)
        return DryRunQueueDecision(
            queue_eligible=True,
            queue_state="ELIGIBLE",
            research_lane=ResearchLane.DISCOVERY_REVIEW.value,
            research_purpose=purpose.value,
            research_priority=40,
            commercial_lifecycle_state=CommercialOpportunityState.REVIEW_REQUIRED.value,
            source_lifecycle_event=source_event.value,
            reason="DISCOVERY_REVIEW_LANE",
            is_active_commercial_lead=False,
            fake_category_allowed=False,
            fake_medal_allowed=False,
        )

    if not track:
        return DryRunQueueDecision(
            queue_eligible=False,
            queue_state="INELIGIBLE",
            research_lane=None,
            research_purpose=None,
            research_priority=0,
            commercial_lifecycle_state=CommercialOpportunityState.REVIEW_REQUIRED.value,
            source_lifecycle_event=source_event.value,
            reason="MISSING_TRACK_AFTER_ROUTING",
            is_active_commercial_lead=False,
        )

    life = _compute_decision(track=track, source_event=source_event)

    if source_event == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME:
        return DryRunQueueDecision(
            queue_eligible=False,
            queue_state="HOLD",
            research_lane=ResearchLane.HOLD.value,
            research_purpose=purpose_for_track(
                track, discovery_review=False, source_event=source_event
            ).value,
            research_priority=0,
            commercial_lifecycle_state=life.commercial_state.value,
            source_lifecycle_event=source_event.value,
            reason="WAITING_SOURCE_OUTCOME_HOLD",
            is_active_commercial_lead=False,
        )

    if source_event == SourceLifecycleEvent.AWARDED and track == "DIRECT_SUPPLY":
        return DryRunQueueDecision(
            queue_eligible=False,
            queue_state="CLOSED_NO_RESEARCH",
            research_lane=ResearchLane.CLOSED_NO_RESEARCH.value,
            research_purpose=None,
            research_priority=0,
            commercial_lifecycle_state=CommercialOpportunityState.CLOSED.value,
            source_lifecycle_event=source_event.value,
            reason="AWARDED_DIRECT_SUPPLY_CLOSED",
            is_active_commercial_lead=False,
        )

    if source_event == SourceLifecycleEvent.AWARDED and track in (
        "EMBEDDED_MATERIAL",
        "DESIGN_REQUIREMENT",
        "DESIGN_INFLUENCE",
    ):
        purpose = purpose_for_track(track, discovery_review=False, source_event=source_event)
        return DryRunQueueDecision(
            queue_eligible=True,
            queue_state="ELIGIBLE",
            research_lane=ResearchLane.AWARDED_FOLLOW_UP.value,
            research_purpose=purpose.value,
            research_priority=60,
            commercial_lifecycle_state=CommercialOpportunityState.FOLLOW_UP_AWARDED.value,
            source_lifecycle_event=source_event.value,
            reason="AWARDED_FOLLOW_UP_RESEARCH",
            is_active_commercial_lead=False,
        )

    if source_event == SourceLifecycleEvent.OPEN:
        purpose = purpose_for_track(track, discovery_review=False, source_event=source_event)
        # DIRECT_SUPPLY open: conditional on research_action not SKIP/METADATA_ONLY
        if track == "DIRECT_SUPPLY":
            action = (research_action or "").upper()
            if action in ("", "SKIP", "METADATA_ONLY"):
                return DryRunQueueDecision(
                    queue_eligible=False,
                    queue_state="INELIGIBLE",
                    research_lane=None,
                    research_purpose=purpose.value,
                    research_priority=0,
                    commercial_lifecycle_state=life.commercial_state.value,
                    source_lifecycle_event=source_event.value,
                    reason="OPEN_DIRECT_SUPPLY_CONDITIONAL_NO_ACTION",
                    is_active_commercial_lead=True,
                )
            return DryRunQueueDecision(
                queue_eligible=True,
                queue_state="ELIGIBLE",
                research_lane=ResearchLane.CRM_ACTIVE_HOT.value
                if action in ("PRIORITY_DOCS", "DEEP_RESEARCH")
                else ResearchLane.OPEN_ACTIVE.value,
                research_purpose=purpose.value,
                research_priority=70 if action in ("PRIORITY_DOCS", "DEEP_RESEARCH") else 30,
                commercial_lifecycle_state=life.commercial_state.value,
                source_lifecycle_event=source_event.value,
                reason="OPEN_DIRECT_SUPPLY_CONDITIONAL_YES",
                is_active_commercial_lead=True,
            )
        if track in ("EMBEDDED_MATERIAL", "DESIGN_REQUIREMENT", "DESIGN_INFLUENCE"):
            return DryRunQueueDecision(
                queue_eligible=True,
                queue_state="ELIGIBLE",
                research_lane=ResearchLane.OPEN_ACTIVE.value,
                research_purpose=purpose.value,
                research_priority=50,
                commercial_lifecycle_state=life.commercial_state.value,
                source_lifecycle_event=source_event.value,
                reason=f"OPEN_{track}_ELIGIBLE",
                is_active_commercial_lead=True,
            )

    return DryRunQueueDecision(
        queue_eligible=False,
        queue_state="INELIGIBLE",
        research_lane=None,
        research_purpose=None,
        research_priority=0,
        commercial_lifecycle_state=life.commercial_state.value,
        source_lifecycle_event=source_event.value,
        reason=f"NO_RULE_MATCH:{source_event.value}:{track}",
        is_active_commercial_lead=False,
    )


def procurement_source_doc_keys(procurement: Dict[str, Any]) -> Dict[str, Any]:
    """Provenance keys for S7 links_documentation_* lookup (read-only)."""
    source_table = str(procurement.get("source_table") or "")
    contour = resolve_source_contour(
        source_table=source_table,
        law_type=str(procurement.get("law_type") or ""),
    )
    return {
        "source_contour": contour.value,
        "source_table": source_table,
        "source_id": procurement.get("source_id"),
        "contract_number": procurement.get("contract_number"),
        "links_table": links_table_for_source(source_table),
        "source_awarded_table": procurement.get("source_awarded_table"),
        "source_awarded_id": procurement.get("source_awarded_id"),
    }
