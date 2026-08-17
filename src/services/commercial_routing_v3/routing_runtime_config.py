"""Production routing runtime constants (V3 sole path)."""
from __future__ import annotations

import os

# Hard production contract: never auto-fallback to V2.
AUTOMATIC_V2_FALLBACK = False
PRODUCTION_REQUIRES_V3 = True

# WAITING_SOURCE_OUTCOME: 0% production capacity. Opt-in only via env.
WAITING_ROUTABLE = os.getenv("CRM_V3_WAITING_ROUTABLE", "0") == "1"

# 7B routing wall-clock evidence: Ollama client timeout ~75s; full item often
# several minutes with DB/persist. Lease = 30m avoids zombie RUNNING while
# remaining shorter than human intervention windows.
ROUTING_PROCESSING_LEASE_SEC = int(
    os.getenv("CRM_V3_ROUTING_PROCESSING_LEASE_SEC", "1800")
)

# Transient failures only; deterministic validation goes to NEEDS_REVIEW.
MAX_ROUTING_ATTEMPTS = int(os.getenv("CRM_V3_ROUTING_MAX_ATTEMPTS", "3"))

# Exponential backoff for FAILED retries (seconds). Caps hammering every 45s drain tick.
FAILED_RETRY_BACKOFF_BASE_SEC = int(os.getenv("CRM_V3_FAILED_RETRY_BACKOFF_BASE_SEC", "300"))
FAILED_RETRY_BACKOFF_MAX_SEC = int(os.getenv("CRM_V3_FAILED_RETRY_BACKOFF_MAX_SEC", "3600"))


def failed_retry_backoff_sec(attempt_count: int) -> int:
    """Backoff before a FAILED row may be selected again."""
    n = max(1, int(attempt_count or 1))
    return min(FAILED_RETRY_BACKOFF_MAX_SEC, FAILED_RETRY_BACKOFF_BASE_SEC * (2 ** (n - 1)))

ENV_V3_RUNTIME = "COMMERCIAL_ROUTING_V3_RUNTIME_ENABLED"


def v3_runtime_enabled() -> bool:
    return os.getenv(ENV_V3_RUNTIME, "0") == "1"


# Error classes for retry matrix
class RoutingErrorClass:
    OLLAMA_TIMEOUT = "OLLAMA_TIMEOUT"
    OLLAMA_UNAVAILABLE = "OLLAMA_UNAVAILABLE"
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    INVALID_CATEGORY = "INVALID_CATEGORY"
    EMPTY_VALID_NO_COMMERCIAL_ENTRY = "EMPTY_VALID_NO_COMMERCIAL_ENTRY"
    UNEXPECTED_EXCEPTION = "UNEXPECTED_EXCEPTION"
    V3_NOT_READY = "V3_NOT_READY"
    V3_DISABLED = "V3_DISABLED"
    SOURCE_INTEGRITY = "SOURCE_INTEGRITY"
    MAX_ATTEMPTS_EXCEEDED = "MAX_ATTEMPTS_EXCEEDED"


TRANSIENT_ERROR_CLASSES = frozenset(
    {
        RoutingErrorClass.OLLAMA_TIMEOUT,
        RoutingErrorClass.OLLAMA_UNAVAILABLE,
        RoutingErrorClass.INVALID_JSON,
        RoutingErrorClass.UNEXPECTED_EXCEPTION,
        RoutingErrorClass.V3_NOT_READY,
    }
)

NONRETRYABLE_ERROR_CLASSES = frozenset(
    {
        RoutingErrorClass.INVALID_CATEGORY,
        RoutingErrorClass.SCHEMA_INVALID,
        RoutingErrorClass.SOURCE_INTEGRITY,
        RoutingErrorClass.EMPTY_VALID_NO_COMMERCIAL_ENTRY,
        RoutingErrorClass.V3_DISABLED,
        RoutingErrorClass.MAX_ATTEMPTS_EXCEEDED,
    }
)
