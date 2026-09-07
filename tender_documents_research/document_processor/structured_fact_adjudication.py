"""Fail-closed rules for independent structured-fact semantic review."""

from typing import Any, Dict, Optional

ADJUDICATION_VERDICTS = {
    "PRODUCT_CORRECT",
    "PRODUCT_INCORRECT",
    "WRONG_ENTITY_TYPE",
    "AMBIGUOUS",
}


def adjudication_allows_trust(record: Optional[Dict[str, Any]]) -> bool:
    """Return true only for a complete independent review that passes all gates."""
    if not record:
        return False
    if record.get("verdict") != "PRODUCT_CORRECT":
        return False
    if record.get("adjudication_method") != "INDEPENDENT_SEMANTIC_REVIEW":
        return False
    return bool(record.get("commercial_type_valid") and record.get("product_evidence_valid"))


def adjudication_metric_verdict(record: Optional[Dict[str, Any]]) -> Optional[str]:
    """Expose only valid independent verdicts to semantic metrics."""
    if not record or record.get("adjudication_method") != "INDEPENDENT_SEMANTIC_REVIEW":
        return None
    verdict = record.get("verdict")
    return verdict if verdict in ADJUDICATION_VERDICTS else None
