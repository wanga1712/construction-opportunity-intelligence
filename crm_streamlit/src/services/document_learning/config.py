"""Document-learning flags. Default off. Automatic skip is forbidden."""
from __future__ import annotations

import os

EXHAUSTIVE_DOCUMENT_DISCOVERY_ENV = "CRM_V3_EXHAUSTIVE_DOCUMENT_DISCOVERY"
EXPLORATION_RATE_ENV = "CRM_V3_DOCUMENT_EXPLORATION_RATE"

AUTOMATIC_SKIP_ENABLED = False
MIN_EXPLORATION_RATE = 0.05
MAX_EXPLORATION_RATE = 0.10
DEFAULT_EXPLORATION_RATE = 0.08


def exhaustive_document_discovery_enabled() -> bool:
    raw = (os.getenv(EXHAUSTIVE_DOCUMENT_DISCOVERY_ENV, "0") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def exploration_rate() -> float:
    raw = os.getenv(EXPLORATION_RATE_ENV, str(DEFAULT_EXPLORATION_RATE))
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        rate = DEFAULT_EXPLORATION_RATE
    return min(MAX_EXPLORATION_RATE, max(MIN_EXPLORATION_RATE, rate))


def automatic_skip_enabled() -> bool:
    return AUTOMATIC_SKIP_ENABLED
