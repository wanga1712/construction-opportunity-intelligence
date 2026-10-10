"""Canonical RESEARCH_ACTION_V2 - one deterministic commercial-entry decision.

This module answers exactly one question per CURRENT category opportunity:

    есть ли opportunity
    -> нужны ли документы вообще
    -> research или confirmation

It is read-only and owns no persistence. The document plan
(``document_needs_plan_v2``) consumes its output; the queue is NOT touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

RESEARCH_ACTION_POLICY_VERSION = "research_action_v2"


class ResearchAction(str, Enum):
    """Canonical RESEARCH_ACTION_V2 enum."""

    NO_OPPORTUNITY = "NO_OPPORTUNITY"
    NO_DOCUMENT_RESEARCH = "NO_DOCUMENT_RESEARCH"
    DOCUMENT_RESEARCH_REQUIRED = "DOCUMENT_RESEARCH_REQUIRED"
    DOCUMENT_CONFIRMATION_REQUIRED = "DOCUMENT_CONFIRMATION_REQUIRED"


TRACK_DIRECT = "DIRECT_SUPPLY"
TRACK_EMBEDDED = frozenset({"EMBEDDED_MATERIAL", "PROJECT"})
TRACK_DESIGN = frozenset({"DESIGN_REQUIREMENT", "DESIGN_INFLUENCE"})
TRACK_NO_ENTRY = frozenset({"NO_COMMERCIAL_ENTRY"})

GROUP_DIRECT = "DIRECT"
GROUP_EMBEDDED = "EMBEDDED"
GROUP_DESIGN = "DESIGN"
GROUP_UNKNOWN = "UNKNOWN"
GROUP_NONE = "NONE"

#: commercial_state values that remove the opportunity entirely.
SUPPRESSED_COMMERCIAL_STATES = frozenset(
    {"SUPERSEDED", "REJECTED", "TERMINAL", "SUPPRESSED", "SOURCE_MISSING", "CANCELLED"}
)
#: commercial_state values that mean "the commercial window is closed".
CLOSED_COMMERCIAL_STATES = frozenset({"CLOSED", "ARCHIVED", "FOLLOW_UP_AWARDED"})

#: medals strong enough that a document is needed only for confirmation.
CONFIRMATION_MEDALS = frozenset({"GOLD", "SILVER"})

DOCUMENT_ACTIONS = frozenset(
    {ResearchAction.DOCUMENT_RESEARCH_REQUIRED, ResearchAction.DOCUMENT_CONFIRMATION_REQUIRED}
)


@dataclass(frozen=True)
class ResearchActionDecision:
    action: ResearchAction
    reason: str
    track_group: str
    policy_version: str = RESEARCH_ACTION_POLICY_VERSION

    @property
    def document_plan_required(self) -> bool:
        return self.action in DOCUMENT_ACTIONS


def track_group(opportunity_track: Optional[str]) -> str:
    track = (opportunity_track or "").strip().upper()
    if track == TRACK_DIRECT:
        return GROUP_DIRECT
    if track in TRACK_EMBEDDED:
        return GROUP_EMBEDDED
    if track in TRACK_DESIGN:
        return GROUP_DESIGN
    if track in TRACK_NO_ENTRY:
        return GROUP_NONE
    return GROUP_UNKNOWN


def decide_research_action(
    *,
    category_code: Optional[str],
    opportunity_track: Optional[str],
    commercial_state: Optional[str] = None,
    commercial_priority: Optional[int] = None,
    candidate_medal: Optional[str] = None,
    has_confirmed_facts: bool = False,
    has_reusable_artifacts: bool = False,
    window_closed: bool = False,
) -> ResearchActionDecision:
    """Deterministic RESEARCH_ACTION_V2 decision.

    ``has_confirmed_facts`` means the required commercial facts for this
    procurement+category are already proven by structured facts / stored
    document evidence (not by a candidate medal).
    """

    group = track_group(opportunity_track)
    state = (commercial_state or "").strip().upper()

    if not (category_code or "").strip():
        return ResearchActionDecision(
            ResearchAction.NO_OPPORTUNITY, "NO_CURRENT_ADMITTED_CATEGORY", group
        )
    if group == GROUP_NONE:
        return ResearchActionDecision(
            ResearchAction.NO_OPPORTUNITY, "NO_COMMERCIAL_ENTRY_TRACK", group
        )
    if state in SUPPRESSED_COMMERCIAL_STATES:
        return ResearchActionDecision(
            ResearchAction.NO_OPPORTUNITY, f"COMMERCIAL_STATE_{state}", group
        )

    if group == GROUP_DIRECT:
        if has_confirmed_facts and has_reusable_artifacts:
            return ResearchActionDecision(
                ResearchAction.NO_DOCUMENT_RESEARCH,
                "DIRECT_FACTS_CONFIRMED_ARTIFACT_REUSABLE",
                group,
            )
        if window_closed and has_confirmed_facts:
            return ResearchActionDecision(
                ResearchAction.NO_DOCUMENT_RESEARCH,
                "DIRECT_WINDOW_CLOSED_AND_FACTS_CONFIRMED",
                group,
            )
        medal = (candidate_medal or "").strip().upper()
        if medal in CONFIRMATION_MEDALS:
            return ResearchActionDecision(
                ResearchAction.DOCUMENT_CONFIRMATION_REQUIRED,
                f"DIRECT_{medal}_CANDIDATE_NEEDS_COMMERCIAL_CONFIRMATION",
                group,
            )
        return ResearchActionDecision(
            ResearchAction.DOCUMENT_RESEARCH_REQUIRED,
            "DIRECT_WEAK_CANDIDATE_NEEDS_RESEARCH",
            group,
        )

    if group in (GROUP_EMBEDDED, GROUP_DESIGN):
        if has_confirmed_facts and has_reusable_artifacts:
            return ResearchActionDecision(
                ResearchAction.NO_DOCUMENT_RESEARCH,
                f"{group}_FACTS_CONFIRMED_ARTIFACT_REUSABLE",
                group,
            )
        return ResearchActionDecision(
            ResearchAction.DOCUMENT_RESEARCH_REQUIRED,
            f"{group}_QUANTITY_AND_CATEGORY_VALUE_UNKNOWN",
            group,
        )

    return ResearchActionDecision(
        ResearchAction.DOCUMENT_RESEARCH_REQUIRED, "TRACK_UNKNOWN_NEEDS_RESEARCH", group
    )
