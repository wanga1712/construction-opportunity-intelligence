"""Analytics V2 command-center snapshot — one bounded read model for the top screen.

The whole top of «Аналитический контур V2» renders from ONE
``AnalyticsCommandSnapshot`` object so that navigating away and back costs
zero DB round-trips while the snapshot is still fresh.

Rules enforced here
-------------------
* Every section carries an ``ok`` flag.  A failed query is NEVER rendered as 0.
* No mock data, no invented metrics: every number comes from a real row.
* Read-only: SELECT statements only.
* Bounded: ~15 queries total; large tables are always reached through indexes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.services.analytics_dashboard_kpi_service import (
    load_dashboard_kpi,
    MEDAL_RANK,
)
from src.services.commercial_routing_v3.submission_window import (
    actionable_submission_sql,
)

logger = logging.getLogger(__name__)

# Fallback labels for commercial categories that are missing from the taxonomy
# registry ``crm_product_categories``.  The registry is the name authority;
# this map covers legacy/derived codes (for example ``computers``) and mirrors
# ``category_opportunity_service.CATEGORY_NAMES``.
CATEGORY_NAMES: Dict[str, str] = {
    "lighting": "Светотехника",
    "flooring": "Напольные покрытия",
    "waterproofing": "Гидроизоляция",
    "waterproofing_concrete_repair": "Гидроизоляция и ремонт бетона",
    "bridge_road_infrastructure": "Мостовая и дорожная инфраструктура",
    "cable_support_systems": "Кабеленесущие системы",
    "composite_structures": "Композитные конструкции",
    "drainage_water_management": "Водоотвод и дренаж",
    "external_utility_networks": "Наружные инженерные сети",
    "structural_reinforcement": "Усиление и ремонт конструкций",
    "curbstone": "Бордюрный камень",
    "concrete_materials": "Материалы для бетона",
    "computers": "Компьютерная техника",
    "composites": "Композиты",
}

# Category matrix contract: a row is rendered only when the category actually
# has opportunities (count > 0).  Categories with zero CURRENT opportunities
# are hidden - a table of zeros is not a business fact - and the panel reports
# how many were hidden.  The cap only guards against a runaway row count; the
# active procurement taxonomy fits inside it.
CATEGORY_MATRIX_MAX_ROWS = 16

MEDAL_ORDER_SQL = (
    "CASE {alias} WHEN 'GOLD' THEN 1 WHEN 'SILVER' THEN 2 "
    "WHEN 'BRONZE' THEN 3 WHEN 'WOOD' THEN 4 ELSE 5 END"
)

# The newest ~300k row ids span far more than 24 h, so bounding the rolling
# window to them keeps the result identical while staying index-only.
_NEW_24H_ID_WINDOW = 300000


# ── Data contracts ────────────────────────────────────────────────────────

@dataclass
class Metric:
    """A single number that may legitimately be unavailable."""
    value: Optional[int] = None
    ok: bool = False

    def display(self) -> Optional[int]:
        return int(self.value) if self.ok and self.value is not None else None


@dataclass
class PipelineNode:
    key: str
    label: str
    value: Optional[int] = None
    ok: bool = False
    hint: str = ""


@dataclass
class PipelineLoss:
    label: str
    value: Optional[int] = None
    ok: bool = False


@dataclass
class CategoryRow:
    code: str
    name: str
    opportunities: int = 0
    medals: Dict[str, int] = field(default_factory=dict)
    actionable: int = 0


@dataclass
class TopOpportunity:
    medal: str
    procurement_number: str
    procurement_name: str
    category_name: str
    value_text: str
    value_label: str
    deadline_text: str


@dataclass
class TransitionCell:
    initial: str
    final: str
    count: int


@dataclass
class HealthItem:
    label: str
    status: str
    timestamp: str = ""


@dataclass
class AnalyticsCommandSnapshot:
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # connection identity
    db_user: str = ""
    db_name: str = ""
    db_host: str = ""
    identity_ok: bool = False

    # freshness (source of truth: last write actually observed in each store)
    crm_last_update: Optional[datetime] = None
    opp_last_update: Optional[datetime] = None
    doc_last_completed: Optional[datetime] = None
    doc_last_enqueued: Optional[datetime] = None

    # active / awarded / new
    active_total: Metric = field(default_factory=Metric)
    active_44: Metric = field(default_factory=Metric)
    active_223: Metric = field(default_factory=Metric)
    active_buckets: Dict[str, Optional[int]] = field(default_factory=dict)

    awarded_44: Metric = field(default_factory=Metric)
    awarded_223: Metric = field(default_factory=Metric)
    awarded_615: Metric = field(default_factory=Metric)

    new_24h_44: Metric = field(default_factory=Metric)
    new_24h_223: Metric = field(default_factory=Metric)
    new_24h_semantics: str = "CRM_INGEST"
    new_source_1d: Metric = field(default_factory=Metric)
    new_source_7d: Metric = field(default_factory=Metric)

    # document pipeline
    pipeline_nodes: List[PipelineNode] = field(default_factory=list)
    pipeline_losses: List[PipelineLoss] = field(default_factory=list)
    doc_status_ok: bool = False

    # category matrix
    categories: List[CategoryRow] = field(default_factory=list)
    categories_ok: bool = False
    # active registry categories hidden because they had zero opportunities
    categories_zero_hidden_names: List[str] = field(default_factory=list)

    # top opportunities
    top_opportunities: List[TopOpportunity] = field(default_factory=list)
    top_ok: bool = False

    # medal transition
    transition: List[TransitionCell] = field(default_factory=list)
    medal_same: Metric = field(default_factory=Metric)
    medal_down: Metric = field(default_factory=Metric)
    medal_up: Metric = field(default_factory=Metric)
    medals_ok: bool = False

    # authority / provenance (only values that actually exist in the data)
    provenance: List[Tuple[str, int]] = field(default_factory=list)
    effective_reasons: List[Tuple[str, int]] = field(default_factory=list)
    authority_ok: bool = False

    # document errors
    doc_no_links: Metric = field(default_factory=Metric)
    doc_failed: Metric = field(default_factory=Metric)
    doc_reasons: List[Tuple[str, int]] = field(default_factory=list)
    doc_errors_ok: bool = False

    # system health (file snapshot, never SSH / hardware probe)
    health: List[HealthItem] = field(default_factory=list)
    health_status: str = ""
    health_ok: bool = False
    health_age_sec: Optional[float] = None

    # accounting
    query_count: int = 0
    query_time_ms: float = 0.0
    errors: List[str] = field(default_factory=list)


# ── helpers ───────────────────────────────────────────────────────────────

def _fetch(cur, sql: str, params: Tuple[Any, ...] = ()) -> List[dict]:
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def _int_or_none(value: Any) -> Optional[int]:
    return None if value is None else int(value)


def _fmt_money(value: Any) -> Tuple[str, str]:
    """Return (text, label).  НМЦК is never presented as potential supply."""
    if value in (None, 0):
        return "—", ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—", ""
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f} млрд ₽", "НМЦК"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f} млн ₽", "НМЦК"
    if number >= 1_000:
        return f"{number / 1_000:.0f} тыс ₽", "НМЦК"
    return f"{number:.0f} ₽", "НМЦК"


# ── section loaders (each isolated: one failure never zeroes the screen) ──

def _load_active(cur, snap: AnalyticsCommandSnapshot) -> None:
    act = actionable_submission_sql("cp")
    rows = _fetch(
        cur,
        "SELECT cp.source_table, count(1) AS cnt FROM crm_procurements cp "
        "WHERE cp.crm_stage = 'torgi' AND cp.award_status = 'submission_open' "
        f"  AND {act} GROUP BY 1 ORDER BY 2 DESC",
    )
    snap.query_count += 1
    by_law = {"44": 0, "223": 0}
    for row in rows:
        src = str(row["source_table"] or "")
        if src.startswith("reestr_contract_44_fz"):
            by_law["44"] += int(row["cnt"])
        elif src.startswith("reestr_contract_223_fz"):
            by_law["223"] += int(row["cnt"])
    snap.active_44 = Metric(by_law["44"], True)
    snap.active_223 = Metric(by_law["223"], True)
    snap.active_total = Metric(by_law["44"] + by_law["223"], True)

    bucket_rows = _fetch(
        cur,
        "SELECT count(1) FILTER (WHERE cp.end_date <= CURRENT_DATE + 2) AS d2, "
        "       count(1) FILTER (WHERE cp.end_date > CURRENT_DATE + 2 "
        "                          AND cp.end_date <= CURRENT_DATE + 5) AS d5, "
        "       count(1) FILTER (WHERE cp.end_date > CURRENT_DATE + 5) AS d6 "
        "FROM crm_procurements cp "
        "WHERE cp.crm_stage = 'torgi' AND cp.award_status = 'submission_open' "
        f"  AND {act}",
    )
    snap.query_count += 1
    if bucket_rows:
        row = bucket_rows[0]
        snap.active_buckets = {
            "до 2 дней": _int_or_none(row.get("d2")),
            "3–5 дней": _int_or_none(row.get("d5")),
            "6+ дней": _int_or_none(row.get("d6")),
        }


def _load_awarded(cur, snap: AnalyticsCommandSnapshot) -> None:
    rows = _fetch(
        cur,
        "SELECT source_table, count(1) AS cnt FROM crm_procurements "
        "WHERE crm_stage = 'razygranye' GROUP BY 1",
    )
    snap.query_count += 1
    awarded = {"44": 0, "223": 0, "615": 0}
    for row in rows:
        src = str(row["source_table"] or "")
        if src.startswith("reestr_contract_44_fz"):
            awarded["44"] += int(row["cnt"])
        elif src.startswith("reestr_contract_223_fz"):
            awarded["223"] += int(row["cnt"])
        elif src.startswith("reestr_contract_615_pp"):
            awarded["615"] += int(row["cnt"])
    snap.awarded_44 = Metric(awarded["44"], True)
    snap.awarded_223 = Metric(awarded["223"], True)
    snap.awarded_615 = Metric(awarded["615"], True)


def _load_new_24h(cur, snap: AnalyticsCommandSnapshot) -> None:
    """Rolling 24 h of CRM ingest plus source-side arrival, in ONE bounded scan.

    ``crm_created_at`` is INGEST time, not first-seen: a re-projection rewrites
    it for rows whose tender started years ago.  The label therefore says
    "loaded into the CRM", and ``start_date`` (the tender's own start date from
    the source register) is carried separately as the authoritative arrival.

    Both values are read from the newest ``_NEW_24H_ID_WINDOW`` ids, which span
    ~34 days of ingest - far more than either 24 h or 7 days - so the one scan
    returns the identical result while staying index-bound.
    """
    rows = _fetch(
        cur,
        "SELECT source_table, "
        "       count(1) FILTER (WHERE crm_created_at >= NOW() - INTERVAL '24 hours') AS n24, "
        "       count(1) FILTER (WHERE start_date >= CURRENT_DATE - 1) AS d1, "
        "       count(1) FILTER (WHERE start_date >= CURRENT_DATE - 7) AS d7 "
        "FROM crm_procurements "
        "WHERE id > (SELECT max(id) - %s FROM crm_procurements) "
        "GROUP BY 1",
        (_NEW_24H_ID_WINDOW,),
    )
    snap.query_count += 1
    fz44 = fz223 = 0
    source_1d = source_7d = 0
    for row in rows:
        src = str(row["source_table"] or "")
        n24 = int(row["n24"] or 0)
        if src.startswith("reestr_contract_44_fz"):
            fz44 += n24
        elif src.startswith("reestr_contract_223_fz"):
            fz223 += n24
        source_1d += int(row["d1"] or 0)
        source_7d += int(row["d7"] or 0)
    snap.new_24h_44 = Metric(fz44, True)
    snap.new_24h_223 = Metric(fz223, True)
    snap.new_source_1d = Metric(source_1d, True)
    snap.new_source_7d = Metric(source_7d, True)


def _load_freshness(cur, snap: AnalyticsCommandSnapshot) -> None:
    rows = _fetch(
        cur,
        "SELECT crm_created_at, crm_updated_at FROM crm_procurements "
        "ORDER BY id DESC LIMIT 1",
    )
    snap.query_count += 1
    if rows:
        snap.crm_last_update = rows[0].get("crm_updated_at") or rows[0].get("crm_created_at")

    rows = _fetch(
        cur, "SELECT max(updated_at) AS m FROM crm_procurement_category_opportunities"
    )
    snap.query_count += 1
    if rows:
        snap.opp_last_update = rows[0].get("m")


def _load_pipeline(cur, snap: AnalyticsCommandSnapshot) -> None:
    rows = _fetch(
        cur,
        "SELECT count(1) FILTER (WHERE candidate_initial_medal IS NOT NULL) AS initial, "
        "       count(1) FILTER (WHERE current_effective_medal IS NOT NULL) AS effective, "
        "       count(1) FILTER (WHERE status = 'CURRENT') AS current_rows, "
        "       count(1) AS total FROM crm_procurement_category_opportunities",
    )
    snap.query_count += 1
    row = rows[0] if rows else {}
    initial = _int_or_none(row.get("initial"))
    effective = _int_or_none(row.get("effective"))
    current_rows = _int_or_none(row.get("current_rows"))

    snap.pipeline_nodes = [
        PipelineNode("actionable", "ЗАКУПКИ · ОТКРЫТ ПРИЁМ",
                     snap.active_total.display(), snap.active_total.ok,
                     "44-ФЗ + 223-ФЗ, каноническое правило actionable"),
        PipelineNode("doc_queue", "ДОКУМЕНТЫ · ОЖИДАЮТ", None, False, ""),
        PipelineNode("doc_done", "ДОКУМЕНТЫ · ОБРАБОТАНЫ", None, False, ""),
        PipelineNode("stage1", "ПЕРВИЧНАЯ ОЦЕНКА", initial, initial is not None, ""),
        PipelineNode("second_pass", "ВТОРОЙ ПРОХОД · ЭФФЕКТИВНАЯ", effective,
                     effective is not None, ""),
        PipelineNode("category", "КАТЕГОРИЙНЫЕ ВОЗМОЖНОСТИ", current_rows,
                     current_rows is not None, ""),
    ]


def _load_registry_categories(
    cur,
) -> Tuple[Dict[str, str], Dict[str, int], List[str]]:
    """Taxonomy registry is the name/order authority for display categories."""
    rows = _fetch(
        cur,
        "SELECT DISTINCT ON (category_code) category_code AS code, "
        "       category_name AS name, sort_order, is_active "
        "FROM crm_product_categories "
        "WHERE contour_code = 'procurement' AND category_code IS NOT NULL "
        "ORDER BY category_code, is_active DESC, registry_version DESC",
    )
    names: Dict[str, str] = {}
    order: Dict[str, int] = {}
    active: List[str] = []
    for row in rows:
        code = str(row["code"])
        names[code] = str(row.get("name") or code)
        order[code] = int(row.get("sort_order") or 0)
        if row.get("is_active"):
            active.append(code)
    return names, order, active


def _category_label(
    code: str, registry_names: Dict[str, str]
) -> str:
    return registry_names.get(code) or CATEGORY_NAMES.get(code, code)


def _load_category_matrix(cur, snap: AnalyticsCommandSnapshot) -> None:
    registry_names, registry_order, active_codes = _load_registry_categories(cur)
    snap.query_count += 1

    medal_rows = _fetch(
        cur,
        "SELECT commercial_category_code AS code, current_effective_medal AS medal, "
        "       count(1) AS cnt FROM crm_procurement_category_opportunities "
        "WHERE status = 'CURRENT' AND commercial_category_code IS NOT NULL "
        "GROUP BY 1, 2 HAVING count(1) > 0",
    )
    snap.query_count += 1
    act = actionable_submission_sql("cp")
    action_rows = _fetch(
        cur,
        "SELECT o.commercial_category_code AS code, count(1) AS cnt "
        "FROM crm_procurement_category_opportunities o "
        "JOIN crm_procurements cp ON cp.id = o.procurement_id "
        "WHERE o.status = 'CURRENT' AND o.commercial_category_code IS NOT NULL "
        "  AND cp.crm_stage = 'torgi' AND cp.award_status = 'submission_open' "
        f"  AND {act} GROUP BY 1 HAVING count(1) > 0",
    )
    snap.query_count += 1
    actionable_by_code = {r["code"]: int(r["cnt"]) for r in action_rows}

    by_code: Dict[str, CategoryRow] = {}
    for row in medal_rows:
        code = str(row["code"])
        entry = by_code.setdefault(
            code, CategoryRow(code=code, name=_category_label(code, registry_names))
        )
        medal = row["medal"]
        cnt = int(row["cnt"])
        entry.opportunities += cnt
        if medal in MEDAL_RANK:
            entry.medals[medal] = entry.medals.get(medal, 0) + cnt
    for code, entry in by_code.items():
        entry.actionable = actionable_by_code.get(code, 0)

    # Query success with count = 0 is reported as 0; a category that never
    # reached an opportunity is simply not a row of this table.
    visible = [row for row in by_code.values() if row.opportunities > 0]
    visible.sort(
        key=lambda row: (-row.opportunities, registry_order.get(row.code, 10_000), row.name)
    )
    snap.categories = visible[:CATEGORY_MATRIX_MAX_ROWS]
    snap.categories_zero_hidden_names = [
        _category_label(code, registry_names)
        for code in sorted(active_codes, key=lambda c: (registry_order.get(c, 10_000), c))
        if code not in by_code
    ]
    snap.categories_ok = True


def _load_top_opportunities(cur, snap: AnalyticsCommandSnapshot) -> None:
    medal_rank = MEDAL_ORDER_SQL.format(alias="o.current_effective_medal")
    rows = _fetch(
        cur,
        "SELECT o.procurement_id, o.current_effective_medal AS medal, "
        "       o.commercial_category_code AS code, o.expected_category_value AS ecv, "
        "       cp.contract_number, cp.auction_name, cp.initial_price, cp.end_date "
        "FROM crm_procurement_category_opportunities o "
        "JOIN crm_procurements cp ON cp.id = o.procurement_id "
        "WHERE o.status = 'CURRENT' "
        f"ORDER BY {medal_rank}, o.commercial_priority_score DESC NULLS LAST, "
        "         COALESCE(o.expected_category_value, cp.initial_price) DESC NULLS LAST, "
        "         o.procurement_id DESC LIMIT 10",
    )
    snap.query_count += 1
    items: List[TopOpportunity] = []
    for row in rows:
        if row.get("ecv") is not None:
            value_text = _fmt_money(row["ecv"])[0]
            value_label = "Потенциальная поставка"
        else:
            value_text, value_label = _fmt_money(row.get("initial_price"))
        deadline = row.get("end_date")
        items.append(
            TopOpportunity(
                medal=str(row.get("medal") or "—"),
                procurement_number=str(row.get("contract_number") or "—"),
                procurement_name=str(row.get("auction_name") or "")[:110],
                category_name=CATEGORY_NAMES.get(str(row.get("code")), str(row.get("code") or "—")),
                value_text=value_text,
                value_label=value_label,
                deadline_text=deadline.strftime("%d.%m.%Y") if deadline else "—",
            )
        )
    snap.top_opportunities = items
    snap.top_ok = True


def _load_medal_transition(cur, snap: AnalyticsCommandSnapshot) -> None:
    rows = _fetch(
        cur,
        "SELECT candidate_initial_medal AS initial, current_effective_medal AS final, "
        "       count(1) AS cnt FROM crm_procurement_category_opportunities "
        "WHERE status = 'CURRENT' "
        "  AND candidate_initial_medal IN ('GOLD','SILVER','BRONZE','WOOD') "
        "  AND current_effective_medal IN ('GOLD','SILVER','BRONZE','WOOD') "
        "GROUP BY 1, 2",
    )
    snap.query_count += 1
    rank = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1}
    same = down = up = 0
    cells: List[TransitionCell] = []
    for row in rows:
        initial, final, cnt = row["initial"], row["final"], int(row["cnt"])
        cells.append(TransitionCell(initial, final, cnt))
        if rank[initial] == rank[final]:
            same += cnt
        elif rank[final] < rank[initial]:
            down += cnt
        else:
            up += cnt
    snap.transition = cells
    snap.medal_same = Metric(same, True)
    snap.medal_down = Metric(down, True)
    snap.medal_up = Metric(up, True)
    snap.medals_ok = True


def _load_authority(cur, snap: AnalyticsCommandSnapshot) -> None:
    prov = _fetch(
        cur,
        "SELECT initial_medal_provenance AS k, count(1) AS cnt "
        "FROM crm_procurement_category_opportunities "
        "WHERE status = 'CURRENT' GROUP BY 1 ORDER BY 2 DESC",
    )
    snap.query_count += 1
    reasons = _fetch(
        cur,
        "SELECT coalesce(current_effective_reason, 'НЕ УКАЗАНО') AS k, count(1) AS cnt "
        "FROM crm_procurement_category_opportunities "
        "WHERE status = 'CURRENT' GROUP BY 1 ORDER BY 2 DESC",
    )
    snap.query_count += 1
    snap.provenance = [(str(r["k"] or "—"), int(r["cnt"])) for r in prov]
    snap.effective_reasons = [(str(r["k"]), int(r["cnt"])) for r in reasons]
    snap.authority_ok = True


def _load_documents(cur, snap: AnalyticsCommandSnapshot) -> None:
    rows = _fetch(
        cur,
        "SELECT status, count(1) AS cnt FROM document_processing_queue GROUP BY 1",
    )
    snap.query_count += 1
    counts: Dict[str, int] = {}
    for row in rows:
        counts[str(row["status"]).upper()] = int(row["cnt"])

    queued = counts.get("PENDING", 0) + counts.get("PRE_RESEARCH_WAITING", 0)
    processed = counts.get("COMPLETED", 0)
    processing = counts.get("PROCESSING", 0)
    failed = counts.get("FAILED", 0)
    no_links = counts.get("NO_LINKS", 0)

    for node in snap.pipeline_nodes:
        if node.key == "doc_queue":
            node.value, node.ok = queued, True
        elif node.key == "doc_done":
            node.value, node.ok = processed, True
    snap.pipeline_losses = [
        PipelineLoss("Нет документов (NO_LINKS)", no_links, True),
        PipelineLoss("Ошибка обработки (FAILED)", failed, True),
        PipelineLoss("В обработке прямо сейчас", processing, True),
    ]
    snap.doc_no_links = Metric(no_links, True)
    snap.doc_failed = Metric(failed, True)
    snap.doc_status_ok = True

    reasons = _fetch(
        cur,
        "SELECT left(coalesce(last_error, '—'), 70) AS err, count(1) AS cnt "
        "FROM document_processing_queue WHERE status = 'FAILED' "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
    )
    snap.query_count += 1
    snap.doc_reasons = [(str(r["err"]), int(r["cnt"])) for r in reasons]
    snap.doc_errors_ok = True

    ts = _fetch(
        cur,
        "SELECT max(completed_at) FILTER (WHERE status = 'COMPLETED') AS done, "
        "       max(created_at) AS queued FROM document_processing_queue",
    )
    snap.query_count += 1
    if ts:
        snap.doc_last_completed = ts[0].get("done")
        snap.doc_last_enqueued = ts[0].get("queued")


# ── system health (file snapshot only — never SSH, never hardware probe) ──

def _load_health(snap: AnalyticsCommandSnapshot) -> None:
    try:
        from src.services.system_health_read import load_dashboard

        view = load_dashboard()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("system health read failed: %s", exc)
        return
    if not view.get("ready"):
        snap.health = [HealthItem("Снимок состояния", "COLLECTOR_DOWN")]
        return

    hosts = (view.get("snapshot") or {}).get("hosts") or {}
    s13 = hosts.get("S13") or {}
    s7 = hosts.get("S7") or {}
    services = {s.get("unit"): s for s in (s13.get("services") or [])}

    def _st(host: Dict[str, Any]) -> str:
        return str(host.get("overall_status") or "UNKNOWN")

    def _svc(unit: str) -> str:
        entry = services.get(unit)
        if not entry:
            return "UNKNOWN"
        return str(entry.get("ui_status") or entry.get("active") or "UNKNOWN")

    ollama = s13.get("ollama") or {}
    ollama_status = "OK" if ollama.get("OLLAMA_SERVICE_ACTIVE") else "DOWN"
    if ollama.get("OLLAMA_ACTIVE_MODEL"):
        ollama_status += f" · {ollama['OLLAMA_ACTIVE_MODEL']}"

    fresh = s7.get("source_freshness") or {}
    s7_ts = str(fresh.get("LATEST_SOURCE_UPDATE") or "")[11:16]

    snap.health = [
        HealthItem("S7 · сборщики ЕИС", _st(s7), s7_ts),
        HealthItem("S13 · PostgreSQL",
                   "OK" if (s13.get("postgres") or {}).get("service_active") else "DOWN"),
        HealthItem("CRM · Streamlit", _svc("crm-streamlit.service")),
        HealthItem("Документы · воркер", _svc("tender-docs-daemon.service")),
        HealthItem("Второй проход · воркер", _svc("crm-v3-autonomous-worker.service")),
        HealthItem("AI · Ollama", ollama_status),
    ]
    snap.health_status = str(view.get("status") or "")
    snap.health_age_sec = view.get("snapshot_age_sec")
    snap.health_ok = True


# ── entry point ───────────────────────────────────────────────────────────

def load_analytics_command_snapshot() -> AnalyticsCommandSnapshot:
    """Build the whole command-center snapshot.  Read-only, bounded, isolated."""
    import time
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs
    from src.services.doc_db_runtime import require_doc_db_connect_kwargs

    t0 = time.monotonic()
    snap = AnalyticsCommandSnapshot()

    # CRM sections
    try:
        kwargs = dict(require_crm_db_connect_kwargs())
        kwargs["connect_timeout"] = 8
        kwargs["options"] = "-c statement_timeout=45000"
        conn = psycopg2.connect(**kwargs)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                snap.db_user = conn.get_dsn_parameters().get("user", "")
                snap.db_name = conn.get_dsn_parameters().get("dbname", "")
                snap.db_host = str(kwargs.get("host"))
                snap.identity_ok = True
                for name, fn in (
                    ("active", _load_active),
                    ("awarded", _load_awarded),
                    ("new24h", _load_new_24h),
                    ("freshness", _load_freshness),
                    ("pipeline", _load_pipeline),
                    ("categories", _load_category_matrix),
                    ("top", _load_top_opportunities),
                    ("medals", _load_medal_transition),
                    ("authority", _load_authority),
                ):
                    try:
                        fn(cur, snap)
                    except Exception as exc:
                        logger.error("command center section %s failed: %s", name, exc)
                        snap.errors.append(f"{name.upper()}_UNAVAILABLE")
        finally:
            conn.close()
    except Exception as exc:
        logger.error("command center CRM connection failed: %s", exc)
        snap.errors.append("CRM_DB_UNREACHABLE")

    # Document sections
    try:
        kwargs = dict(require_doc_db_connect_kwargs())
        kwargs["connect_timeout"] = 8
        kwargs["options"] = "-c statement_timeout=30000"
        conn = psycopg2.connect(**kwargs)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _load_documents(cur, snap)
        finally:
            conn.close()
    except Exception as exc:
        logger.error("command center document connection failed: %s", exc)
        snap.errors.append("DOC_DB_UNREACHABLE")

    _load_health(snap)

    snap.query_time_ms = (time.monotonic() - t0) * 1000
    return snap


def load_dashboard_kpi_bridge():
    """Expose the legacy KPI loader for diagnostics/technical expander."""
    return load_dashboard_kpi