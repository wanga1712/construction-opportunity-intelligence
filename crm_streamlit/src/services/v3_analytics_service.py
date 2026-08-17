"""V3 live analytics — READ ONLY aggregates for Streamlit dashboard.

Capability levels:
  A — S7 source + current CRM (available now)
  B — V3 routing schema/tables (auto when present; see v3_analytics_level_b)
  C — document confirmation (contract only until pipeline)

No DB writes. No fake numbers.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.domain.commercial_opportunity_lifecycle import CommercialOpportunityState
from src.domain.commercial_routing_v3 import (
    CandidateMedal,
    OpportunityTrack,
    ProcurementForm,
    ROUTING_VERSION,
)
from src.services.commercial_routing_v3.projection import (
    VISIBLE_OPPORTUNITY_STATES,
    active_feed_includes_procurement,
)
from src.services.commercial_routing_v3.schema_readiness import check_v3_schema_readiness

ANALYTICS_DB_WRITES = 0
FAKE_ANALYTICS_VALUES = 0
POST_CUTOVER_UI_REWRITE_REQUIRED = False
POST_ROUTING_UI_REWRITE_REQUIRED = False
CONFIRMED_MEDAL_UI_CONTRACT_READY = True

DASHBOARD_INITIAL_QUERY_COUNT = 3
CATEGORY_ANALYTICS_QUERY_COUNT = 1

VISIBLE_ACTIVE_STATES = frozenset(VISIBLE_OPPORTUNITY_STATES)

PROCUREMENT_FORM_LABELS_RU = {
    ProcurementForm.DIRECT_GOODS_PURCHASE.value: "Прямая поставка",
    ProcurementForm.CONSTRUCTION_WORKS.value: "Строительные работы",
    ProcurementForm.DESIGN_ONLY.value: "Проектирование",
    ProcurementForm.SURVEY_AND_DESIGN.value: "ПИР",
    ProcurementForm.DESIGN_AND_BUILD.value: "Проект + строительство",
    ProcurementForm.DESIGN_EXPERTISE_AND_BUILD.value: "Проект + экспертиза + строительство",
    ProcurementForm.WORKS_OTHER.value: "Прочее (работы)",
    ProcurementForm.SERVICES_OTHER.value: "Прочее (услуги)",
    ProcurementForm.UNKNOWN.value: "Не определено",
}

TRACK_LABELS_RU = {
    OpportunityTrack.DIRECT_SUPPLY.value: "Прямая поставка",
    OpportunityTrack.EMBEDDED_MATERIAL.value: "В составе работ",
    OpportunityTrack.DESIGN_REQUIREMENT.value: "Проектная потребность",
    OpportunityTrack.DESIGN_INFLUENCE.value: "Проектное влияние",
    OpportunityTrack.NO_COMMERCIAL_ENTRY.value: "Без коммерческого входа",
    OpportunityTrack.UNKNOWN.value: "Не определён",
}

MEDAL_ORDER = (
    CandidateMedal.GOLD.value,
    CandidateMedal.SILVER.value,
    CandidateMedal.BRONZE.value,
    CandidateMedal.WOOD.value,
)

COMMERCIAL_TRACKS = (
    OpportunityTrack.DIRECT_SUPPLY.value,
    OpportunityTrack.EMBEDDED_MATERIAL.value,
    OpportunityTrack.DESIGN_REQUIREMENT.value,
    OpportunityTrack.DESIGN_INFLUENCE.value,
)


@dataclass
class V3AnalyticsSnapshot:
    """Level A always filled; B/C empty/zero until schema/routing/docs."""

    level_a_ok: bool = True
    level_b_ready: bool = False
    level_c_ready: bool = False
    warnings: List[str] = field(default_factory=list)
    v3_missing: List[str] = field(default_factory=list)

    source_44_open: int = 0
    source_223_open: int = 0
    source_44_waiting: int = 0
    source_223_waiting: int = 0
    source_44_awarded_all: int = 0
    source_223_awarded_all: int = 0
    source_open: int = 0
    source_waiting: int = 0
    awarded_history_excluded: int = 0

    crm_projected: int = 0
    crm_torgi: int = 0
    crm_razygranye: int = 0
    crm_okpd_nonnull: int = 0
    crm_okpd_null: int = 0
    target_v3_eligible_approx: int = 0
    not_yet_projected_approx: int = 0

    routed_procurements: int = 0
    procurements_with_opportunities: int = 0
    total_opportunities: int = 0
    active_leads: int = 0
    candidate_gold: Optional[int] = None
    candidate_silver: Optional[int] = None
    candidate_bronze: Optional[int] = None
    candidate_wood: Optional[int] = None
    discovery_required: Optional[int] = None
    pending_routing: int = 0
    no_current_opportunity: int = 0
    review_required: int = 0

    lifecycle: Dict[str, int] = field(default_factory=dict)
    tracks: Dict[str, Dict[str, int]] = field(default_factory=dict)
    forms: Dict[str, int] = field(default_factory=dict)
    category_rows: List[Dict[str, Any]] = field(default_factory=list)

    okpd_priors_status: str = "NOT_DEPLOYED"
    title_signals_status: str = "NOT_DEPLOYED"
    positive_title_signals: int = 0
    negative_title_signals: int = 0
    hard_exclusions: int = 0

    failures: Dict[str, int] = field(default_factory=dict)
    versions: Dict[str, Any] = field(default_factory=dict)
    confirmed_status: str = "Нет данных подтверждения"
    confirmed_medals: Dict[str, int] = field(default_factory=dict)
    multi_category: Dict[str, int] = field(default_factory=dict)
    avg_opportunities_per_procurement: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _scalar(db, sql: str, params: Any = None) -> int:
    try:
        rows = db.execute_query(sql, params) if params is not None else db.execute_query(sql)
        if not rows:
            return 0
        row = rows[0]
        if isinstance(row, dict):
            return int(next(iter(row.values())) or 0)
        return int(row[0] or 0)
    except Exception:
        return 0


def _safe_query(db, sql: str, params: Any = None) -> List[Dict[str, Any]]:
    try:
        rows = db.execute_query(sql, params) if params is not None else db.execute_query(sql)
        out: List[Dict[str, Any]] = []
        for r in rows or []:
            if isinstance(r, dict):
                out.append(dict(r))
            else:
                out.append({"_0": r[0]} if r is not None else {})
        return out
    except Exception:
        return []


def _empty_tracks() -> Dict[str, Dict[str, int]]:
    return {
        t: {"procurements": 0, "opportunities": 0, **{m: 0 for m in MEDAL_ORDER}}
        for t in COMMERCIAL_TRACKS
    }


def _apply_contour_filter(snap: V3AnalyticsSnapshot, contour: str) -> None:
    if contour == "44":
        snap.source_open = snap.source_44_open
        snap.source_waiting = snap.source_44_waiting
        snap.awarded_history_excluded = snap.source_44_awarded_all
        snap.target_v3_eligible_approx = snap.source_44_open + snap.source_44_waiting
    elif contour == "223":
        snap.source_open = snap.source_223_open
        snap.source_waiting = snap.source_223_waiting
        snap.awarded_history_excluded = snap.source_223_awarded_all
        snap.target_v3_eligible_approx = snap.source_223_open + snap.source_223_waiting
    else:
        snap.source_open = snap.source_44_open + snap.source_223_open
        snap.source_waiting = snap.source_44_waiting + snap.source_223_waiting
        snap.awarded_history_excluded = snap.source_44_awarded_all + snap.source_223_awarded_all
        snap.target_v3_eligible_approx = snap.source_open + snap.source_waiting


def load_live_snapshot(
    tender_db,
    crm_db,
    *,
    contour: str = "ALL",
    category: str = "ALL",
    track: str = "ALL",
    medal: str = "ALL",
    lifecycle: str = "ALL",
) -> V3AnalyticsSnapshot:
    """Build analytics snapshot. Filters apply to Level B when data exists."""
    snap = V3AnalyticsSnapshot()
    warnings: List[str] = []

    if not tender_db:
        warnings.append("S7 source DB недоступна")
        snap.level_a_ok = False
    if not crm_db:
        warnings.append("CRM DB недоступна")
        snap.level_a_ok = False

    if tender_db:
        try:
            snap.source_44_open = _scalar(tender_db, "SELECT count(*) FROM reestr_contract_44_fz")
            snap.source_223_open = _scalar(tender_db, "SELECT count(*) FROM reestr_contract_223_fz")
            snap.source_44_waiting = _scalar(
                tender_db, "SELECT count(*) FROM reestr_contract_44_fz_commission_work"
            )
            snap.source_223_waiting = _scalar(
                tender_db, "SELECT count(*) FROM reestr_contract_223_fz_commission_work"
            )
            snap.source_44_awarded_all = _scalar(
                tender_db, "SELECT count(*) FROM reestr_contract_44_fz_awarded"
            )
            snap.source_223_awarded_all = _scalar(
                tender_db, "SELECT count(*) FROM reestr_contract_223_fz_awarded"
            )
        except Exception as exc:
            warnings.append(f"Source metrics error: {exc}")
            snap.level_a_ok = False

    _apply_contour_filter(snap, contour)

    if crm_db:
        try:
            snap.crm_projected = _scalar(crm_db, "SELECT count(*) FROM crm_procurements")
            for row in _safe_query(
                crm_db,
                "SELECT crm_stage AS stage, count(*) AS c FROM crm_procurements GROUP BY 1",
            ):
                stg = str(row.get("stage") or "")
                c = int(row.get("c") or 0)
                if stg == "torgi":
                    snap.crm_torgi = c
                elif stg == "razygranye":
                    snap.crm_razygranye = c
            snap.crm_okpd_nonnull = _scalar(
                crm_db,
                "SELECT count(*) FROM crm_procurements "
                "WHERE okpd_code IS NOT NULL AND btrim(okpd_code) <> ''",
            )
            snap.crm_okpd_null = max(0, snap.crm_projected - snap.crm_okpd_nonnull)
        except Exception as exc:
            warnings.append(f"CRM metrics error: {exc}")
            snap.level_a_ok = False

    snap.not_yet_projected_approx = max(0, snap.target_v3_eligible_approx - snap.crm_projected)
    snap.pending_routing = snap.crm_projected
    snap.active_leads = 0
    snap.lifecycle = {s.value: 0 for s in CommercialOpportunityState}
    snap.tracks = _empty_tracks()
    snap.forms = {k: 0 for k in PROCUREMENT_FORM_LABELS_RU}
    snap.confirmed_medals = {m: 0 for m in MEDAL_ORDER}
    snap.multi_category = {"0": 0, "1": 0, "2": 0, "3": 0, "4+": 0}
    snap.versions = {
        "routing_version": ROUTING_VERSION,
        "prompt_version": "v3_category_centric_routing",
        "v3_schema_active": False,
        "registry_version": "—",
        "registry_hash": "—",
        "current_version_assessments": 0,
        "stale_version_assessments": 0,
        "status": "V3 schema not active",
    }
    snap.failures = {
        "V3_NOT_READY": 1,
        "MODEL_ERROR": 0,
        "VALIDATION_ERROR": 0,
        "ROUTING_FAILED": 0,
        "PERSISTENCE_FAILED": 0,
        "PENDING_ROUTING": snap.pending_routing,
        "PENDING_REASSESSMENT": 0,
        "STALE_ASSESSMENT": 0,
    }

    if crm_db:
        try:
            readiness = check_v3_schema_readiness(crm_db)
            snap.level_b_ready = bool(readiness.ready)
            snap.v3_missing = list(readiness.missing or [])
        except Exception as exc:
            warnings.append(f"V3 readiness check failed: {exc}")
            snap.level_b_ready = False

    if not snap.level_b_ready:
        snap.okpd_priors_status = "NOT_DEPLOYED"
        snap.title_signals_status = "NOT_DEPLOYED"
        snap.hard_exclusions = 0
        snap.candidate_gold = None
        snap.candidate_silver = None
        snap.candidate_bronze = None
        snap.candidate_wood = None
        snap.discovery_required = None
        snap.warnings = warnings
        return snap

    from src.services.v3_analytics_level_b import enrich_level_b

    enrich_level_b(
        snap,
        crm_db,
        contour=contour,
        category=category,
        track=track,
        medal=medal,
        lifecycle=lifecycle,
    )
    snap.warnings = warnings
    return snap


def medal_badge_label(medal: str, *, confirmed: bool = False) -> str:
    m = (medal or "").upper()
    kind = "CONFIRMED" if confirmed else "CANDIDATE"
    return f"[{m}] [{kind}]"


def is_active_lead_opportunities(opportunities: Sequence[Dict[str, Any]]) -> bool:
    return active_feed_includes_procurement(list(opportunities), v3_schema_ready=True)


def closed_direct_is_active(commercial_state: str, track: str) -> bool:
    if (
        track == OpportunityTrack.DIRECT_SUPPLY.value
        and commercial_state == CommercialOpportunityState.CLOSED.value
    ):
        return False
    return commercial_state in VISIBLE_ACTIVE_STATES


def followup_awarded_is_active(commercial_state: str) -> bool:
    return commercial_state == CommercialOpportunityState.FOLLOW_UP_AWARDED.value


def format_optional_metric(value: Optional[int], *, awaiting: str = "Ожидает маршрутизации") -> str:
    if value is None:
        return awaiting
    return str(value)


# Re-exports for tests / callers
from src.services.v3_analytics_fixtures import (  # noqa: E402
    build_fixture_opportunities,
    summarize_fixture_analytics,
)
