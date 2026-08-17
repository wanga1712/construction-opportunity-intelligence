"""Category-centric routing signals — separate from document matcher stop phrases."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def load_routing_signals(crm_db, *, category_code: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = """
        SELECT commercial_category_code, signal_type, signal_scope, phrase,
               active, provenance, registry_version
        FROM crm_category_routing_signals
        WHERE active = TRUE
    """
    params: list = []
    if category_code:
        sql += " AND commercial_category_code = %s"
        params.append(category_code)
    sql += " ORDER BY commercial_category_code, signal_type"
    rows = crm_db.execute_query(sql, tuple(params) if params else None) or []
    return [dict(r) if isinstance(r, dict) else {} for r in rows]


def apply_title_signals(
    title: str,
    signals: List[Dict[str, Any]],
    category_code: str,
) -> Dict[str, List[str]]:
    """Apply routing signals to title. Default stop-word → NEGATIVE_SIGNAL, not HARD_EXCLUSION."""
    title_l = (title or "").lower()
    result: Dict[str, List[str]] = {
        "positive_evidence": [],
        "negative_evidence": [],
        "hard_exclusions": [],
        "context_signals": [],
    }
    for sig in signals:
        if sig.get("commercial_category_code") != category_code:
            continue
        phrase = (sig.get("phrase") or "").lower().strip()
        if not phrase or phrase not in title_l:
            continue
        stype = (sig.get("signal_type") or "NEGATIVE_SIGNAL").upper()
        if stype == "POSITIVE_SIGNAL":
            result["positive_evidence"].append(phrase)
        elif stype == "HARD_EXCLUSION":
            result["hard_exclusions"].append(phrase)
        elif stype == "CONTEXT_SIGNAL":
            result["context_signals"].append(phrase)
        else:
            result["negative_evidence"].append(phrase)
    return result
