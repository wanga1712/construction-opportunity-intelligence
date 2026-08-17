"""Read-only diagnostics: queue state and daily processing quality metrics."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Source-type classification (derived from table_source column)
# ---------------------------------------------------------------------------

_AWARDED_MARKERS = ("_awarded", "_completed")
_COMMISSION_MARKERS = ("_commission_work", "_615_pp")
_OPEN_SUFFIXES = ("_44_fz", "_223_fz")

CATEGORY_OPEN = "OPEN"
CATEGORY_AWARDED = "AWARDED"
CATEGORY_COMMISSION = "COMMISSION"
CATEGORY_OTHER = "Другое"

_KNOWN_CATEGORIES = {CATEGORY_OPEN, CATEGORY_AWARDED, CATEGORY_COMMISSION, CATEGORY_OTHER}


def classify_table_source(source: str) -> str:
    """Map table_source value to a display category."""
    s = (source or "").lower()
    if any(m in s for m in _AWARDED_MARKERS):
        return CATEGORY_AWARDED
    if any(m in s for m in _COMMISSION_MARKERS):
        return CATEGORY_COMMISSION
    if any(s.endswith(sfx) for sfx in _OPEN_SUFFIXES):
        return CATEGORY_OPEN
    return CATEGORY_OTHER


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

WARN_HIGH_NO_LINKS = "no_links_rate_high"
WARN_DOMINANT_CATEGORY = "dominant_category"
WARN_OPEN_STARVED = "open_starved"
WARN_EVIDENCE_SPIKE = "evidence_spike"
WARN_STUCK_PROCESSING = "stuck_processing"

NO_LINKS_THRESHOLD = 0.50
DOMINANT_CATEGORY_THRESHOLD = 0.70
STARVED_THRESHOLD = 5
EVIDENCE_SPIKE_THRESHOLD = 20.0


@dataclass
class QualityWarning:
    code: str
    message: str


def compute_warnings(
    *,
    no_links_rate: Optional[float],
    category_shares: Dict[str, float],
    open_completed: int,
    evidence_per_match: Optional[float],
    stuck_count: int,
) -> List[QualityWarning]:
    warnings: List[QualityWarning] = []

    if no_links_rate is not None and no_links_rate > NO_LINKS_THRESHOLD:
        pct = round(no_links_rate * 100, 1)
        warnings.append(QualityWarning(
            WARN_HIGH_NO_LINKS,
            f"no_links rate {pct}% превышает порог {int(NO_LINKS_THRESHOLD * 100)}%",
        ))

    for cat, share in category_shares.items():
        if share > DOMINANT_CATEGORY_THRESHOLD:
            pct = round(share * 100, 1)
            warnings.append(QualityWarning(
                WARN_DOMINANT_CATEGORY,
                f"Категория {cat} занимает {pct}% обработки (порог {int(DOMINANT_CATEGORY_THRESHOLD * 100)}%)",
            ))

    if open_completed <= STARVED_THRESHOLD and open_completed >= 0:
        warnings.append(QualityWarning(
            WARN_OPEN_STARVED,
            f"OPEN закупок обработано мало: {open_completed} (порог ≤{STARVED_THRESHOLD})",
        ))

    if evidence_per_match is not None and evidence_per_match > EVIDENCE_SPIKE_THRESHOLD:
        warnings.append(QualityWarning(
            WARN_EVIDENCE_SPIKE,
            f"evidence на match аномально велико: {evidence_per_match:.1f} (норма ≤{EVIDENCE_SPIKE_THRESHOLD})",
        ))

    if stuck_count > 0:
        warnings.append(QualityWarning(
            WARN_STUCK_PROCESSING,
            f"{stuck_count} задач в статусе processing без прогресса более 2 часов",
        ))

    return warnings


# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------

@dataclass
class QualityMetrics:
    total_terminal: int = 0
    completed: int = 0
    no_links: int = 0
    error: int = 0
    expired: int = 0

    no_links_rate: Optional[float] = None
    error_rate: Optional[float] = None

    # Breakdown by source category
    by_category: Dict[str, int] = field(default_factory=dict)
    category_shares: Dict[str, float] = field(default_factory=dict)

    # Match/evidence (None if data unavailable)
    tenders_with_matches: Optional[int] = None
    total_matches: Optional[int] = None
    total_evidence: Optional[int] = None
    docs_per_task: Optional[float] = None
    matches_per_task: Optional[float] = None
    evidence_per_match: Optional[float] = None

    warnings: List[QualityWarning] = field(default_factory=list)
    match_data_available: bool = False


def _safe_rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator == 0:
        return None
    return numerator / denominator


def compute_quality_metrics(
    *,
    status_by_category: Dict[str, Dict[str, int]],
    match_rows: Optional[List[dict]],
    stuck_count: int,
) -> QualityMetrics:
    """
    status_by_category: {category: {status: count}}
    match_rows: [{registry_type, match_count, evidence_count, tender_count}] or None
    """
    m = QualityMetrics()

    all_counts: Dict[str, int] = {}
    for cat, statuses in status_by_category.items():
        cat_total = 0
        for status, cnt in statuses.items():
            all_counts[status] = all_counts.get(status, 0) + cnt
            cat_total += cnt
        m.by_category[cat] = cat_total

    m.completed = all_counts.get("completed", 0)
    m.no_links = all_counts.get("no_links", 0)
    m.error = all_counts.get("error", 0)
    m.expired = all_counts.get("sales_window_expired", 0)
    m.total_terminal = m.completed + m.no_links + m.error + m.expired

    m.no_links_rate = _safe_rate(m.no_links, m.total_terminal)
    m.error_rate = _safe_rate(m.error, m.total_terminal)

    total_cat = sum(m.by_category.values())
    if total_cat > 0:
        m.category_shares = {cat: cnt / total_cat for cat, cnt in m.by_category.items()}

    if match_rows is not None:
        m.match_data_available = True
        total_matches = sum(r.get("match_count") or 0 for r in match_rows)
        total_evidence = sum(r.get("evidence_count") or 0 for r in match_rows)
        tenders_with_matches = sum(r.get("tender_count") or 0 for r in match_rows)
        m.total_matches = total_matches
        m.total_evidence = total_evidence
        m.tenders_with_matches = tenders_with_matches
        m.matches_per_task = _safe_rate(total_matches, m.total_terminal)
        m.evidence_per_match = _safe_rate(total_evidence, total_matches) if total_matches else None

    open_completed = (status_by_category.get(CATEGORY_OPEN) or {}).get("completed", 0)
    m.warnings = compute_warnings(
        no_links_rate=m.no_links_rate,
        category_shares=m.category_shares,
        open_completed=open_completed,
        evidence_per_match=m.evidence_per_match,
        stuck_count=stuck_count,
    )

    return m


# ---------------------------------------------------------------------------
# Database queries (read-only)
# ---------------------------------------------------------------------------

def _to_dict(row, columns: tuple) -> dict:
    """Convert a tuple row to dict. Pass-through if already dict-like."""
    if isinstance(row, tuple):
        return dict(zip(columns, row))
    return dict(row)


def get_queue_snapshot(tender_db) -> dict:
    """
    One query: aggregate status × lane × source × worker_id.
    Returns structured dict ready for UI.
    """
    if not tender_db:
        return {"ok": False, "error": "Tender DB not connected"}
    try:
        rows = tender_db.execute_query(
            """
            SELECT
                status,
                COALESCE(queue_lane, 'unknown')   AS queue_lane,
                COALESCE(queue_source, 'unknown') AS queue_source,
                worker_id,
                COUNT(*) AS cnt
            FROM document_processing_queue
            GROUP BY status, queue_lane, queue_source, worker_id
            """
        ) or []
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    by_status: Dict[str, int] = {}
    by_lane: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    active_workers: set = set()

    _cols = ("status", "queue_lane", "queue_source", "worker_id", "cnt")
    for raw in rows:
        r = _to_dict(raw, _cols)
        status = r.get("status") or "unknown"
        lane = r.get("queue_lane") or "unknown"
        source = r.get("queue_source") or "unknown"
        cnt = int(r.get("cnt") or 0)
        worker_id = r.get("worker_id")

        by_status[status] = by_status.get(status, 0) + cnt

        # Lane and source breakdown only for active items
        if status in ("pending", "processing"):
            by_lane[lane] = by_lane.get(lane, 0) + cnt
            by_source[source] = by_source.get(source, 0) + cnt

        if status == "processing" and worker_id is not None:
            active_workers.add(worker_id)

    return {
        "ok": True,
        "by_status": by_status,
        "by_lane": by_lane,
        "by_source": by_source,
        "active_workers": sorted(active_workers),
    }


def get_daily_stats(tender_db, day: date) -> dict:
    """
    One query: terminal-status rows for the selected day, grouped by status × table_source.
    Uses COALESCE(completed_at, created_at) as the event date.
    """
    if not tender_db:
        return {"ok": False, "error": "Tender DB not connected"}
    try:
        rows = tender_db.execute_query(
            """
            SELECT
                status,
                COALESCE(table_source, 'unknown') AS table_source,
                COUNT(*) AS cnt
            FROM document_processing_queue
            WHERE status IN ('completed', 'error', 'no_links', 'sales_window_expired')
              AND COALESCE(completed_at, created_at)::date = %s
            GROUP BY status, table_source
            """,
            (day,),
        ) or []
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    # Aggregate into {category: {status: count}}
    _cols2 = ("status", "table_source", "cnt")
    status_by_category: Dict[str, Dict[str, int]] = {}
    for raw in rows:
        r = _to_dict(raw, _cols2)
        cat = classify_table_source(r.get("table_source") or "")
        status = r.get("status") or "unknown"
        cnt = int(r.get("cnt") or 0)
        status_by_category.setdefault(cat, {})[status] = (
            status_by_category.get(cat, {}).get(status, 0) + cnt
        )

    return {"ok": True, "status_by_category": status_by_category}


def get_daily_matches(tender_db, day: date) -> dict:
    """
    One query over tender_document_matches + match_details for the selected day.
    Returns None data if the table or created_at column is unavailable.
    """
    if not tender_db:
        return {"ok": False, "rows": None}
    try:
        rows = tender_db.execute_query(
            """
            SELECT
                m.registry_type,
                COUNT(DISTINCT m.id)        AS match_count,
                COUNT(d.id)                 AS evidence_count,
                COUNT(DISTINCT m.tender_id) AS tender_count
            FROM tender_document_matches m
            LEFT JOIN tender_document_match_details d ON d.match_id = m.id
            WHERE m.is_interesting = TRUE
              AND m.created_at::date = %s
            GROUP BY m.registry_type
            """,
            (day,),
        )
        _cols3 = ("registry_type", "match_count", "evidence_count", "tender_count")
        return {"ok": True, "rows": [_to_dict(r, _cols3) for r in (rows or [])]}
    except Exception:
        return {"ok": True, "rows": None}


def get_stuck_processing(tender_db) -> dict:
    """Tasks stuck in processing for more than 2 hours (requires started_at column)."""
    if not tender_db:
        return {"ok": False, "count": 0}
    try:
        rows = tender_db.execute_query(
            """
            SELECT COUNT(*) AS cnt
            FROM document_processing_queue
            WHERE status = 'processing'
              AND started_at < NOW() - INTERVAL '2 hours'
            """
        ) or []
        row0 = _to_dict(rows[0], ("cnt",)) if rows else {}
        count = int(row0.get("cnt") or 0)
        return {"ok": True, "count": count}
    except Exception:
        return {"ok": True, "count": 0}
