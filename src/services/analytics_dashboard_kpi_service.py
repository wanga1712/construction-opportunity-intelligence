"""Analytics Dashboard KPI Service — factual DB-backed metrics.

Single-query-per-section design.  No mock data.  No N+1.

Sections
--------
1. Array counts — 44-FZ / 223-FZ × torgi / razygranye
2. New in rolling 24 h — same groups, filter by crm_created_at
3. Document pipeline status — from document_processing_queue
4. Medal transition matrix — from crm_procurement_category_opportunities

All queries are SELECT-only (read-only).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Law and stage mapping ────────────────────────────────────────────────

_SOURCE_TO_LAW: Dict[str, str] = {
    "reestr_contract_44_fz": "44-ФЗ",
    "reestr_contract_44_fz_awarded": "44-ФЗ",
    "reestr_contract_223_fz": "223-ФЗ",
    "reestr_contract_223_fz_commission_work": "223-ФЗ",
}

_STAGE_DISPLAY: Dict[str, str] = {
    "torgi": "Идут торги",
    "razygranye": "Разыгранные",
}

# ── Medal ordering ────────────────────────────────────────────────────────

MEDAL_ORDER: Dict[str, int] = {
    "GOLD": 4,
    "SILVER": 3,
    "BRONZE": 2,
    "WOOD": 1,
}

MEDAL_RANK = ("GOLD", "SILVER", "BRONZE", "WOOD")

VALID_MEDALS = frozenset(MEDAL_RANK)


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class ArrayCounts:
    """Procurement counts by law × stage."""
    fz44_torgi: int = 0
    fz223_torgi: int = 0
    fz44_razygranye: int = 0
    fz223_razygranye: int = 0

    @property
    def total(self) -> int:
        return self.fz44_torgi + self.fz223_torgi + self.fz44_razygranye + self.fz223_razygranye


@dataclass
class PipelineStatus:
    """Document processing queue status counts."""
    queued: int = 0       # PENDING + PRE_RESEARCH_WAITING
    processing: int = 0   # PROCESSING
    processed: int = 0    # COMPLETED
    failed: int = 0       # FAILED
    no_links: int = 0     # NO_LINKS

    @property
    def rejected_available(self) -> bool:
        """ОТКЛОНЕНО is SOURCE_GAP — no pipeline status directly maps."""
        return False


@dataclass
class MedalTransition:
    """Single cell of the 4×4 transition matrix."""
    preliminary: str
    final: str
    count: int


@dataclass
class MedalDecisions:
    """Medal transition summary and matrix."""
    same: int = 0
    down: int = 0
    up: int = 0
    rejected: int = 0
    matrix: List[MedalTransition] = field(default_factory=list)

    @property
    def total_decided(self) -> int:
        return self.same + self.down + self.up

    @property
    def matrix_sum(self) -> int:
        return sum(t.count for t in self.matrix)

    @property
    def invariant_pass(self) -> bool:
        """SAME + DOWN + UP == SUM(16 matrix cells)."""
        return self.total_decided == self.matrix_sum

    def same_pct(self) -> float:
        return (self.same / self.total_decided * 100) if self.total_decided else 0.0

    def down_pct(self) -> float:
        return (self.down / self.total_decided * 100) if self.total_decided else 0.0

    def up_pct(self) -> float:
        return (self.up / self.total_decided * 100) if self.total_decided else 0.0

    def matrix_grid(self) -> Dict[Tuple[str, str], int]:
        """Return {(preliminary, final): count} for all 16 cells."""
        grid: Dict[Tuple[str, str], int] = {}
        for p in MEDAL_RANK:
            for f in MEDAL_RANK:
                grid[(p, f)] = 0
        for t in self.matrix:
            grid[(t.preliminary, t.final)] = t.count
        return grid


@dataclass
class DashboardKPI:
    """Complete dashboard KPI snapshot."""
    array: ArrayCounts = field(default_factory=ArrayCounts)
    new_24h: ArrayCounts = field(default_factory=ArrayCounts)
    pipeline: PipelineStatus = field(default_factory=PipelineStatus)
    medals: MedalDecisions = field(default_factory=MedalDecisions)
    last_sync_at: Optional[datetime] = None
    query_count: int = 0
    query_time_ms: float = 0.0

    # SOURCE_GAP tracking
    source_gaps: List[str] = field(default_factory=list)


# ── Query helpers ─────────────────────────────────────────────────────────

def _classify_transition(preliminary: str, final: str) -> str:
    """Classify a medal transition as SAME, DOWN, or UP."""
    p_rank = MEDAL_ORDER.get(preliminary, 0)
    f_rank = MEDAL_ORDER.get(final, 0)
    if p_rank == f_rank:
        return "SAME"
    elif f_rank < p_rank:
        return "DOWN"
    else:
        return "UP"


def _map_law(source_table: str) -> Optional[str]:
    """Map source_table to law label, or None if unknown."""
    return _SOURCE_TO_LAW.get(source_table)


def _apply_array_row(
    arr: ArrayCounts,
    source_table: str,
    crm_stage: str,
    count: int,
) -> None:
    """Apply a single grouped row to the ArrayCounts accumulator."""
    law = _map_law(source_table)
    if law is None:
        return
    if law == "44-ФЗ" and crm_stage == "torgi":
        arr.fz44_torgi += count
    elif law == "223-ФЗ" and crm_stage == "torgi":
        arr.fz223_torgi += count
    elif law == "44-ФЗ" and crm_stage == "razygranye":
        arr.fz44_razygranye += count
    elif law == "223-ФЗ" and crm_stage == "razygranye":
        arr.fz223_razygranye += count


# ── Main loader ───────────────────────────────────────────────────────────

def load_dashboard_kpi(crm_db: Any, doc_db_connect: Any = None) -> DashboardKPI:
    """Load all dashboard KPIs with bounded query count.

    Parameters
    ----------
    crm_db
        CRM database connection/manager with ``execute_query(sql, params)``.
    doc_db_connect
        Callable returning a psycopg2 connection to the document DB
        (``tender_monitor`` / ``document_intelligence``).
        If None, pipeline section returns zeros and registers SOURCE_GAP.
    """
    import time
    t0 = time.monotonic()
    kpi = DashboardKPI()
    queries = 0

    # ── Section 1: Array counts ──────────────────────────────────────────
    try:
        rows = crm_db.execute_query(
            "SELECT source_table, crm_stage, count(1) AS cnt "
            "FROM crm_procurements "
            "WHERE crm_stage IN ('torgi', 'razygranye') "
            "GROUP BY source_table, crm_stage",
            (),
        )
        queries += 1
        for r in (rows or []):
            if isinstance(r, dict):
                _apply_array_row(kpi.array, r["source_table"], r["crm_stage"], int(r["cnt"]))
            elif isinstance(r, (list, tuple)) and len(r) >= 3:
                _apply_array_row(kpi.array, r[0], r[1], int(r[2]))
    except Exception as e:
        logger.error("Dashboard KPI array counts failed: %s", e)

    # ── Section 2: New in 24h (rolling) ──────────────────────────────────
    try:
        rows = crm_db.execute_query(
            "SELECT source_table, crm_stage, count(1) AS cnt "
            "FROM crm_procurements "
            "WHERE crm_stage IN ('torgi', 'razygranye') "
            "  AND crm_created_at >= NOW() - INTERVAL '24 hours' "
            "GROUP BY source_table, crm_stage",
            (),
        )
        queries += 1
        for r in (rows or []):
            if isinstance(r, dict):
                _apply_array_row(kpi.new_24h, r["source_table"], r["crm_stage"], int(r["cnt"]))
            elif isinstance(r, (list, tuple)) and len(r) >= 3:
                _apply_array_row(kpi.new_24h, r[0], r[1], int(r[2]))
    except Exception as e:
        logger.error("Dashboard KPI new-24h failed: %s", e)

    # ── Last sync timestamp ──────────────────────────────────────────────
    try:
        rows = crm_db.execute_query(
            "SELECT max(crm_created_at) FROM crm_procurements",
            (),
        )
        queries += 1
        if rows:
            r = rows[0]
            val = r[0] if isinstance(r, (list, tuple)) else r.get("max") if isinstance(r, dict) else None
            if val is not None:
                if isinstance(val, datetime):
                    kpi.last_sync_at = val
                else:
                    kpi.last_sync_at = datetime.fromisoformat(str(val))
    except Exception as e:
        logger.error("Dashboard KPI last sync timestamp failed: %s", e)

    # ── Section 3: Document pipeline ─────────────────────────────────────
    if doc_db_connect is not None:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            conn = doc_db_connect()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        "SELECT status, count(1) AS cnt "
                        "FROM document_processing_queue "
                        "GROUP BY status"
                    )
                    queries += 1
                    for row in cur.fetchall():
                        status = row["status"]
                        cnt = int(row["cnt"])
                        if status in ("PENDING", "PRE_RESEARCH_WAITING", "pending"):
                            kpi.pipeline.queued += cnt
                        elif status in ("PROCESSING", "processing"):
                            kpi.pipeline.processing += cnt
                        elif status in ("COMPLETED", "completed"):
                            kpi.pipeline.processed += cnt
                        elif status in ("FAILED", "failed"):
                            kpi.pipeline.failed += cnt
                        elif status in ("NO_LINKS", "no_links"):
                            kpi.pipeline.no_links += cnt
            finally:
                conn.close()
        except Exception as e:
            logger.error("Dashboard KPI pipeline query failed: %s", e)
            kpi.source_gaps.append("PIPELINE_DB_UNREACHABLE")
    else:
        kpi.source_gaps.append("PIPELINE_DB_NOT_CONFIGURED")

    # ОТКЛОНЕНО is always SOURCE_GAP — no pipeline status maps to
    # "documents did not confirm commercial opportunity"
    kpi.source_gaps.append("KPI_SOURCE_REJECTED=SOURCE_GAP")

    # ── Section 4: Medal transitions ─────────────────────────────────────
    try:
        rows = crm_db.execute_query(
            "SELECT candidate_initial_medal, current_effective_medal, count(1) AS cnt "
            "FROM crm_procurement_category_opportunities "
            "WHERE candidate_initial_medal IN ('GOLD','SILVER','BRONZE','WOOD') "
            "  AND current_effective_medal IN ('GOLD','SILVER','BRONZE','WOOD') "
            "  AND commercial_state != 'REJECTED' "
            "GROUP BY candidate_initial_medal, current_effective_medal",
            (),
        )
        queries += 1
        for r in (rows or []):
            if isinstance(r, dict):
                pre = r["candidate_initial_medal"]
                fin = r["current_effective_medal"]
                cnt = int(r["cnt"])
            elif isinstance(r, (list, tuple)) and len(r) >= 3:
                pre, fin, cnt = r[0], r[1], int(r[2])
            else:
                continue

            if pre in VALID_MEDALS and fin in VALID_MEDALS:
                kpi.medals.matrix.append(MedalTransition(pre, fin, cnt))
                direction = _classify_transition(pre, fin)
                if direction == "SAME":
                    kpi.medals.same += cnt
                elif direction == "DOWN":
                    kpi.medals.down += cnt
                else:
                    kpi.medals.up += cnt
    except Exception as e:
        logger.error("Dashboard KPI medal transitions failed: %s", e)

    # Rejected count
    try:
        rows = crm_db.execute_query(
            "SELECT count(1) AS cnt "
            "FROM crm_procurement_category_opportunities "
            "WHERE commercial_state = 'REJECTED'",
            (),
        )
        queries += 1
        if rows:
            r = rows[0]
            kpi.medals.rejected = int(r[0] if isinstance(r, (list, tuple)) else r.get("cnt", 0))
    except Exception as e:
        logger.error("Dashboard KPI rejected count failed: %s", e)

    kpi.query_count = queries
    kpi.query_time_ms = (time.monotonic() - t0) * 1000
    return kpi
