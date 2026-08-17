"""S7→S13 commercial opportunity lifecycle domain model.

This domain layer is pure: no SQL, no persistence, no AI/queue/doc processing.
"""

from __future__ import annotations

from enum import StrEnum


class SourceLifecycleEvent(StrEnum):
    OPEN = "OPEN"
    WAITING_SOURCE_OUTCOME = "WAITING_SOURCE_OUTCOME"
    AWARDED = "AWARDED"
    TERMINAL_NO_RESULT = "TERMINAL_NO_RESULT"
    UNKNOWN = "UNKNOWN"


class CommercialOpportunityState(StrEnum):
    ACTIVE = "ACTIVE"
    WAITING_SOURCE_OUTCOME = "WAITING_SOURCE_OUTCOME"
    FOLLOW_UP_AWARDED = "FOLLOW_UP_AWARDED"
    CLOSED = "CLOSED"

    # Retention / learning lane
    ARCHIVED = "ARCHIVED"
    STALE_SOURCE = "STALE_SOURCE"

    # Policy/control lanes
    SUPPRESSED = "SUPPRESSED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

