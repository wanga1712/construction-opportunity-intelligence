"""Queue-first first layer for the CRM analytics contour (read-only, bounded).

The first screen of the contour is the real commercial queue. Membership and
order come from production truth; nothing is recomputed in the UI:

* ``document_processing_queue`` (``pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'``)
  supplies queue membership, the production score/band and the research state.
* ``crm_procurement_scope_authority`` (``admission_state='ELIGIBLE'`` and
  ``admission_policy_version='BUSINESS_RESEARCH_ADMISSION_V2'``) is the only
  admission authority.
* ``crm_procurements`` supplies the cheap lifecycle/customer/region/price fields.
* ``crm_procurement_category_opportunities`` (``status='CURRENT'``) supplies the
  commercial medal layer when it exists; it is never a UI-side decision.

The document DB and the CRM DB are separate databases on the same cluster, so a
page is built with ONE bounded scan query + small batched lookups (never a full
ID dump, never per-card round-trips).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.doc_db_runtime import require_doc_db_connect_kwargs

logger = logging.getLogger(__name__)

PIPELINE_GENERATION = "S13_V4_EXHAUSTIVE_CONTEXT"
ADMISSION_POLICY = "BUSINESS_RESEARCH_ADMISSION_V2"
ADMISSION_ELIGIBLE = "ELIGIBLE"

DEFAULT_PAGE_SIZE = 20
SCAN_BATCH = 400
MAX_SCAN_PER_PAGE = 2000

MEDAL_RANK = {"GOLD": 1, "SILVER": 2, "BRONZE": 3, "WOOD": 4}

SCOPE_LABEL = {
    "DIRECT_GOODS": "DIRECT",
    "DIRECT_GOODS_PURCHASE": "DIRECT",
    "WORKS_WITH_EMBEDDED_PRODUCTS": "WORKS",
    "WORKS": "WORKS",
    "EQUIPMENT_AND_INSTALLATION": "WORKS",
    "DESIGN_PROJECT": "DESIGN",
    "DESIGN": "DESIGN",
    "PURE_SERVICE": "SERVICE",
    "SERVICE_WITH_CONSUMABLES": "SERVICE",
    "MIXED": "MIXED",
}

RESEARCH_STATE_LABEL = {
    "PRE_RESEARCH_WAITING": "ожидает обработки",
    "PENDING": "ожидает обработки",
    "PROCESSING": "обрабатывается",
    "RUNNING": "обрабатывается",
    "COMPLETED": "документы обработаны",
    "FAILED": "ошибка обработки",
    "NO_LINKS": "нет ссылок на документы",
}


class QueueFirstUnavailable(RuntimeError):
    """Raised when the queue-first layer cannot be built from production truth."""


# ── Query fragments ─────────────────────────────────────────────────────────

_LANE_RANK_SQL = """
    CASE q.queue_lane
        WHEN 'crm_active_hot' THEN 1
        WHEN 'open_active' THEN 2
        WHEN 'awarded_recent' THEN 3
        WHEN 'historical_awarded' THEN 4
        ELSE 5
    END
"""

_BAND_RANK_SQL = """
    CASE q.research_prior_band
        WHEN 'GOLD' THEN 1
        WHEN 'SILVER' THEN 2
        WHEN 'BRONZE' THEN 3
        WHEN 'WOOD' THEN 4
        ELSE 5
    END
"""


def _doc_scan_sql(after_cursor: Optional[Tuple[int, int, int, int, int]]) -> str:
    where_cursor = ""
    if after_cursor is not None:
        where_cursor = (
            "WHERE (t.lane_rank, t.band_rank, t.neg_eff, t.neg_prio, t.row_id) "
            "> (%s, %s, %s, %s, %s)"
        )
    return f"""
        SELECT * FROM (
            SELECT q.id AS row_id,
                   q.procurement_id,
                   q.status,
                   q.queue_lane,
                   q.priority_score,
                   q.research_prior_band,
                   q.research_prior_score,
                   q.research_prior_percentile,
                   q.research_prior_effective_score,
                   q.category_codes,
                   q.candidate_level,
                   q.candidate_score,
                   q.research_action,
                   q.normalized_nmck_rub,
                   {_LANE_RANK_SQL} AS lane_rank,
                   {_BAND_RANK_SQL} AS band_rank,
                   (- COALESCE(q.research_prior_effective_score, q.priority_score, 0)) AS neg_eff,
                   (- COALESCE(q.priority_score, 0)) AS neg_prio
              FROM document_processing_queue q
             WHERE q.pipeline_generation = %s
        ) t
        {where_cursor}
        ORDER BY t.lane_rank, t.band_rank, t.neg_eff, t.neg_prio, t.row_id
        LIMIT %s
    """


def _cursor_of(row: Dict[str, Any]) -> Tuple[int, int, int, int, int]:
    return (row["lane_rank"], row["band_rank"], row["neg_eff"], row["neg_prio"], row["row_id"])


# ── Data contracts ──────────────────────────────────────────────────────────

@dataclass
class QueueFilters:
    medal: Optional[str] = None       # GOLD/SILVER/BRONZE/WOOD
    lifecycle: Optional[str] = None   # OPEN/AWARDED
    scope: Optional[str] = None       # DIRECT/WORKS/DESIGN
    category: Optional[str] = None    # commercial_category_code
    region: Optional[str] = None


@dataclass
class QueueCard:
    procurement_id: int
    row_id: int
    title: Optional[str] = None
    contract_number: Optional[str] = None
    lifecycle: str = "UNKNOWN"
    scope_type: str = "UNKNOWN"
    scope_label: str = "—"
    medal: Optional[str] = None
    medal_layer: str = "NONE"          # CONFIRMED / PRELIMINARY / NONE
    priority: Optional[int] = None
    research_prior_band: Optional[str] = None
    research_state: str = "UNKNOWN"
    research_state_label: str = "—"
    categories: List[str] = field(default_factory=list)
    category_codes: List[str] = field(default_factory=list)
    nmck: Optional[float] = None
    contract_price: Optional[float] = None
    end_date: Optional[date] = None
    execution_end_at: Optional[date] = None
    customer: Optional[str] = None
    region: Optional[str] = None
    why_now: Optional[str] = None
    admission_state: str = "UNKNOWN"
    tender_link: Optional[str] = None
    object_type: Optional[str] = None
    current_effective_reason: Optional[str] = None
    cursor: Optional[Tuple[int, int, int, int, int]] = None


@dataclass
class QueuePage:
    cards: List[QueueCard]
    next_cursor: Optional[Tuple[int, int, int, int, int]]
    metrics: Dict[str, Any]


# ── Connections ─────────────────────────────────────────────────────────────

def _open_doc():
    kwargs = require_doc_db_connect_kwargs()
    kwargs["connect_timeout"] = 5
    kwargs["options"] = "-c statement_timeout=20000"
    conn = psycopg2.connect(**kwargs)
    conn.autocommit = True
    return conn


def _open_crm():
    kwargs = require_crm_db_connect_kwargs()
    kwargs["connect_timeout"] = 5
    kwargs["options"] = "-c statement_timeout=20000"
    conn = psycopg2.connect(**kwargs)
    conn.autocommit = True
    return conn


def open_doc_connection():
    """Public opener so the UI can cache a long-lived document-DB connection."""
    return _open_doc()


def open_crm_connection():
    """Public opener so the UI can cache a long-lived CRM-DB connection."""
    return _open_crm()


def load_queue_snapshot(doc_conn: Any = None, crm_conn: Any = None) -> Dict[str, Any]:
    """Cheap production snapshot for the summary row (3 bounded aggregates).

    * document queue (S13_V4) grouped by status — how much is processed now;
    * CURRENT commercial opportunities grouped by best medal per procurement —
      how many active cards are stored in the DB by GOLD/SILVER/BRONZE/WOOD;
    * ELIGIBLE admission authority grouped by lifecycle — how many are OPEN
      («идут торги») and AWARDED.
    """
    own_doc = doc_conn is None
    own_crm = crm_conn is None
    if own_doc:
        doc_conn = _open_doc()
    if own_crm:
        crm_conn = _open_crm()
    snapshot: Dict[str, Any] = {
        "queue_total": 0,
        "waiting": 0,
        "processing": 0,
        "processed": 0,
        "errors": 0,
        "active_cards": 0,
        "medals": {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "WOOD": 0, "NONE": 0},
        "open": 0,
        "awarded": 0,
        "terminal": 0,
    }
    try:
        with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT status, count(*) AS n FROM document_processing_queue "
                "WHERE pipeline_generation = %s GROUP BY status",
                (PIPELINE_GENERATION,),
            )
            for r in cur.fetchall():
                n = int(r["n"])
                status = r["status"]
                snapshot["queue_total"] += n
                if status in ("PRE_RESEARCH_WAITING", "PENDING"):
                    snapshot["waiting"] += n
                elif status in ("PROCESSING", "RUNNING"):
                    snapshot["processing"] += n
                elif status == "COMPLETED":
                    snapshot["processed"] += n
                elif status in ("FAILED", "NO_LINKS"):
                    snapshot["errors"] += n

        with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT COALESCE(medal, 'NONE') AS medal, count(*) AS n FROM (
                    SELECT (ARRAY_AGG(
                        COALESCE(
                            NULLIF(current_effective_medal, ''),
                            NULLIF(candidate_medal, ''),
                            NULLIF(confirmed_base_medal, '')
                        )
                        ORDER BY CASE COALESCE(
                            NULLIF(current_effective_medal, ''),
                            NULLIF(candidate_medal, ''),
                            NULLIF(confirmed_base_medal, '')
                        )
                            WHEN 'GOLD' THEN 1 WHEN 'SILVER' THEN 2
                            WHEN 'BRONZE' THEN 3 WHEN 'WOOD' THEN 4 ELSE 5 END
                    ))[1] AS medal
                      FROM crm_procurement_category_opportunities
                     WHERE status = 'CURRENT'
                     GROUP BY procurement_id
                ) t GROUP BY 1
                """
            )
            for r in cur.fetchall():
                key = r["medal"] if r["medal"] in snapshot["medals"] else "NONE"
                snapshot["medals"][key] += int(r["n"])
            snapshot["active_cards"] = sum(snapshot["medals"].values())

            cur.execute(
                "SELECT source_lifecycle, count(*) AS n "
                "FROM crm_procurement_scope_authority "
                "WHERE admission_state = %s AND admission_policy_version = %s "
                "GROUP BY source_lifecycle",
                (ADMISSION_ELIGIBLE, ADMISSION_POLICY),
            )
            for r in cur.fetchall():
                n = int(r["n"])
                lifecycle = str(r["source_lifecycle"] or "").upper()
                if lifecycle == "OPEN":
                    snapshot["open"] += n
                elif lifecycle == "AWARDED":
                    snapshot["awarded"] += n
                elif lifecycle == "TERMINAL_NO_RESULT":
                    snapshot["terminal"] += n
    finally:
        if own_doc:
            doc_conn.close()
        if own_crm:
            crm_conn.close()
    return snapshot


# ── Page load ───────────────────────────────────────────────────────────────

def load_queue_page(
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    after_cursor: Optional[Sequence[int]] = None,
    filters: Optional[QueueFilters] = None,
    doc_conn: Any = None,
    crm_conn: Any = None,
) -> QueuePage:
    """Build one bounded page of the queue-first first layer."""
    filters = filters or QueueFilters()
    own_doc = doc_conn is None
    own_crm = crm_conn is None
    if own_doc:
        doc_conn = _open_doc()
    if own_crm:
        crm_conn = _open_crm()
    queries = 0
    doc_ms = 0.0
    crm_ms = 0.0
    scanned = 0
    eligible_seen = 0
    cards: List[QueueCard] = []
    next_cursor: Optional[Tuple[int, int, int, int, int]] = (
        tuple(after_cursor) if after_cursor else None
    )
    try:
        seen_pids: set = set()
        while len(cards) < page_size and scanned < MAX_SCAN_PER_PAGE:
            batch = min(SCAN_BATCH, MAX_SCAN_PER_PAGE - scanned)
            t0 = time.perf_counter()
            with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                params: List[Any] = [PIPELINE_GENERATION]
                if next_cursor is not None:
                    params.extend(list(next_cursor))
                params.append(batch)
                cur.execute(_doc_scan_sql(next_cursor), params)
                rows = [dict(r) for r in cur.fetchall()]
            queries += 1
            doc_ms += (time.perf_counter() - t0) * 1000.0
            if not rows:
                break

            t0 = time.perf_counter()
            ctx = _batch_crm(rows, crm_conn)
            queries += 3  # authority + procurements + current opportunities
            crm_ms += (time.perf_counter() - t0) * 1000.0

            for row in rows:
                scanned += 1
                pid = int(row["procurement_id"])
                next_cursor = _cursor_of(row)
                if pid in seen_pids:
                    continue
                seen_pids.add(pid)
                card = _build_card(row, ctx)
                if card.admission_state != ADMISSION_ELIGIBLE:
                    continue
                eligible_seen += 1
                if not _passes_filters(card, filters):
                    continue
                cards.append(card)
                if len(cards) >= page_size:
                    break
    finally:
        if own_doc:
            doc_conn.close()
        if own_crm:
            crm_conn.close()

    return QueuePage(
        cards=cards,
        next_cursor=next_cursor,
        metrics={
            "first_queue_query_ms": round(doc_ms, 1),
            "crm_lookup_ms": round(crm_ms, 1),
            "db_queries": queries,
            "scanned_rows": scanned,
            "eligible_seen": eligible_seen,
            "page_size": page_size,
        },
    )


def _batch_crm(rows: Sequence[Dict[str, Any]], conn: Any = None) -> Dict[str, Any]:
    ids = sorted({int(r["procurement_id"]) for r in rows})
    ctx: Dict[str, Any] = {
        "authority": {},
        "procurements": {},
        "opportunities": {},
        "category_names": {},
    }
    own = conn is None
    if own:
        conn = _open_crm()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT procurement_id, admission_state, admission_policy_version,
                       procurement_scope_type, source_lifecycle, scope_confidence
                  FROM crm_procurement_scope_authority
                 WHERE procurement_id = ANY(%s)
                """,
                (ids,),
            )
            for r in cur.fetchall():
                ctx["authority"][r["procurement_id"]] = dict(r)

            cur.execute(
                """
                SELECT id, auction_name, contract_number, customer, delivery_region,
                       initial_price, final_price, final_contract_price, crm_stage,
                       award_status, end_date, delivery_end_date, execution_start_at,
                       execution_end_at, tender_link, object_type
                  FROM crm_procurements
                 WHERE id = ANY(%s)
                """,
                (ids,),
            )
            for r in cur.fetchall():
                ctx["procurements"][r["id"]] = dict(r)

            cur.execute(
                """
                SELECT procurement_id, commercial_category_code, commercial_subcategory_code,
                       opportunity_track, candidate_medal, confirmed_base_medal,
                       current_effective_medal, research_priority, commercial_priority_score,
                       current_effective_score, current_effective_reason, commercial_state,
                       research_action
                  FROM crm_procurement_category_opportunities
                 WHERE status = 'CURRENT' AND procurement_id = ANY(%s)
                """,
                (ids,),
            )
            for r in cur.fetchall():
                ctx["opportunities"].setdefault(r["procurement_id"], []).append(dict(r))

            cur.execute(
                "SELECT category_code, category_name FROM crm_product_categories "
                "WHERE is_active = True"
            )
            for r in cur.fetchall():
                ctx["category_names"][r["category_code"]] = r["category_name"]
    finally:
        if own:
            conn.close()
    return ctx


def _best_medal(opps: Sequence[Dict[str, Any]], key: str) -> Optional[str]:
    ranked = [o.get(key) for o in opps if o.get(key) in MEDAL_RANK]
    if not ranked:
        return None
    return min(ranked, key=lambda m: MEDAL_RANK[m])


def _lifecycle_of(authority: Dict[str, Any], procurement: Dict[str, Any]) -> str:
    src = str((authority or {}).get("source_lifecycle") or "").upper()
    if src in ("OPEN", "AWARDED"):
        return src
    if src == "TERMINAL_NO_RESULT":
        return "CLOSED"
    award = str((procurement or {}).get("award_status") or "").lower()
    stage = str((procurement or {}).get("crm_stage") or "").lower()
    if award == "awarded" or stage == "razygranye":
        return "AWARDED"
    if stage == "torgi":
        return "OPEN"
    return "UNKNOWN"


def _why_now(row: Dict[str, Any], opps: Sequence[Dict[str, Any]]) -> str:
    reasons = [str(o.get("current_effective_reason") or "").strip() for o in opps]
    reasons = [r for r in reasons if r]
    if reasons:
        return reasons[0]
    band = row.get("research_prior_band")
    score = row.get("research_prior_effective_score")
    if score is None:
        score = row.get("priority_score")
    if band and score is not None:
        return f"research_prior={band} · score={int(score)}"
    if score is not None:
        return f"priority={int(score)}"
    return "—"


def _build_card(row: Dict[str, Any], ctx: Dict[str, Any]) -> QueueCard:
    pid = int(row["procurement_id"])
    authority = ctx["authority"].get(pid, {})
    procurement = ctx["procurements"].get(pid, {})
    opps = ctx["opportunities"].get(pid, [])
    names = ctx["category_names"]

    confirmed = _best_medal(opps, "current_effective_medal") or _best_medal(
        opps, "confirmed_base_medal"
    )
    candidate = _best_medal(opps, "candidate_medal") or (
        row.get("candidate_level") if row.get("candidate_level") in MEDAL_RANK else None
    )
    if confirmed:
        medal, layer = confirmed, "CONFIRMED"
    elif candidate:
        medal, layer = candidate, "PRELIMINARY"
    else:
        medal, layer = None, "NONE"

    codes = [c for c in (row.get("category_codes") or []) if c]
    opp_codes = [
        o.get("commercial_category_code")
        for o in opps
        if o.get("commercial_category_code")
    ]
    ordered_codes = list(dict.fromkeys(opp_codes + codes))

    scope_type = str(
        (authority or {}).get("procurement_scope_type")
        or row.get("procurement_scope_type")
        or "UNKNOWN"
    )
    state = str(row.get("status") or "UNKNOWN")
    priority = row.get("research_prior_effective_score")
    if priority is None:
        priority = row.get("priority_score")
    row_cursor = _cursor_of(row)

    return QueueCard(
        procurement_id=pid,
        row_id=int(row["row_id"]),
        title=procurement.get("auction_name") or row.get("contract_number"),
        contract_number=procurement.get("contract_number") or row.get("contract_number"),
        lifecycle=_lifecycle_of(authority, procurement),
        scope_type=scope_type,
        scope_label=SCOPE_LABEL.get(scope_type, scope_type.replace("_", " ")),
        medal=medal,
        medal_layer=layer,
        priority=int(priority) if priority is not None else None,
        research_prior_band=row.get("research_prior_band"),
        research_state=state,
        research_state_label=RESEARCH_STATE_LABEL.get(state, state),
        categories=[names.get(c, c.replace("_", " ")) for c in ordered_codes[:4]],
        category_codes=ordered_codes,
        nmck=_num(procurement.get("initial_price"))
        or _num(procurement.get("final_price"))
        or _num(row.get("normalized_nmck_rub")),
        contract_price=_num(procurement.get("final_contract_price"))
        or _num(procurement.get("final_price")),
        end_date=procurement.get("end_date") or procurement.get("delivery_end_date"),
        execution_end_at=procurement.get("execution_end_at"),
        customer=procurement.get("customer"),
        region=procurement.get("delivery_region"),
        why_now=_why_now(row, opps),
        admission_state=str((authority or {}).get("admission_state") or "UNKNOWN"),
        tender_link=procurement.get("tender_link"),
        object_type=procurement.get("object_type"),
        current_effective_reason=(opps[0].get("current_effective_reason") if opps else None),
        cursor=row_cursor,
    )


def _num(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _passes_filters(card: QueueCard, f: QueueFilters) -> bool:
    if f.medal and card.medal != f.medal:
        return False
    if f.lifecycle and card.lifecycle != f.lifecycle:
        return False
    if f.scope and card.scope_label != f.scope:
        return False
    if f.category and f.category not in card.category_codes:
        return False
    if f.region and (card.region or "") != f.region:
        return False
    return True


# ── Cheap lookups for the UI ────────────────────────────────────────────────

def load_category_options(crm_conn: Any = None) -> List[Dict[str, str]]:
    """Active commercial categories (code + name) — a lightweight filter list."""
    conn = crm_conn or _open_crm()
    own = crm_conn is None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT category_code, category_name FROM crm_product_categories "
                "WHERE is_active = True ORDER BY sort_order, category_code"
            )
            return [{"code": c, "name": n or c} for c, n in cur.fetchall()]
    finally:
        if own:
            conn.close()


def load_region_options(limit: int = 60, crm_conn: Any = None) -> List[str]:
    """Most frequent delivery regions — bounded, single aggregate query."""
    conn = crm_conn or _open_crm()
    own = crm_conn is None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT delivery_region FROM crm_procurements "
                "WHERE delivery_region IS NOT NULL AND delivery_region <> '' "
                "GROUP BY delivery_region ORDER BY count(*) DESC, delivery_region LIMIT %s",
                (limit,),
            )
            return [r[0] for r in cur.fetchall()]
    finally:
        if own:
            conn.close()


# ── Lazy detail (loaded only after a card is opened) ────────────────────────

def load_card_detail(procurement_id: int, crm_conn: Any = None) -> Dict[str, Any]:
    """Detail payload for one card — no documents, no AI payload, no history."""
    conn = crm_conn or _open_crm()
    own = crm_conn is None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT admission_state, admission_policy_version, procurement_scope_type, "
                "source_lifecycle, scope_confidence, scope_method "
                "FROM crm_procurement_scope_authority WHERE procurement_id = %s",
                (procurement_id,),
            )
            authority = dict(cur.fetchone() or {})
            cur.execute(
                "SELECT id, auction_name, contract_number, customer, delivery_region, "
                "initial_price, final_price, final_contract_price, crm_stage, award_status, "
                "start_date, end_date, delivery_start_date, delivery_end_date, "
                "execution_start_at, execution_end_at, tender_link, object_type, "
                "file_count, match_count, evidence_count "
                "FROM crm_procurements WHERE id = %s",
                (procurement_id,),
            )
            procurement = dict(cur.fetchone() or {})
            cur.execute(
                "SELECT commercial_category_code, commercial_subcategory_code, opportunity_track, "
                "candidate_medal, confirmed_base_medal, current_effective_medal, research_priority, "
                "commercial_priority_score, current_effective_score, current_effective_reason, "
                "commercial_state, research_action, reason_codes, candidate_initial_medal "
                "FROM crm_procurement_category_opportunities "
                "WHERE status = 'CURRENT' AND procurement_id = %s "
                "ORDER BY commercial_priority_score DESC NULLS LAST",
                (procurement_id,),
            )
            opportunities = [dict(r) for r in cur.fetchall()]
        return {
            "authority": authority,
            "procurement": procurement,
            "opportunities": opportunities,
        }
    finally:
        if own:
            conn.close()


def backend_top_ids(page_size: int = 20) -> List[int]:
    """The production queue top IDs used for the UI acceptance comparison."""
    return [c.procurement_id for c in load_queue_page(page_size=page_size).cards]


def load_card_ai_history(procurement_id: int, crm_conn: Any = None) -> Dict[str, Any]:
    """Lazy AI/assessment + manual-audit layer for one card (bounded)."""
    conn = crm_conn or _open_crm()
    own = crm_conn is None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT assessment_version, status, model_version, prompt_version, "
                "proposed_route_profile, proposed_object_type, proposed_procurement_type, "
                "proposed_categories, proposed_level, confidence, reasons, reason_codes, "
                "completed_at, is_stale "
                "FROM procurement_ai_assessments WHERE procurement_id = %s "
                "ORDER BY is_current DESC, id DESC LIMIT 1",
                (procurement_id,),
            )
            assessment = dict(cur.fetchone() or {})
            cur.execute(
                "SELECT action_type, user_name, comment, changed_fields, timestamp, "
                "approved_for_training FROM crm_manual_assessments_audit "
                "WHERE procurement_id = %s ORDER BY timestamp DESC LIMIT 20",
                (procurement_id,),
            )
            history = [dict(r) for r in cur.fetchall()]
        return {"assessment": assessment, "history": history}
    finally:
        if own:
            conn.close()
