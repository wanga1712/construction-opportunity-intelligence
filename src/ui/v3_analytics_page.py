"""Streamlit page: Аналитика V3 — performance-safe OKPD funnel.

Normal load: snapshot once per rerun; paginated OKPD; lazy sections/drilldown.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import streamlit as st

from src.domain.commercial_opportunity_lifecycle import CommercialOpportunityState
from src.services.v3_analytics_precutover import (
    PreCutoverFileCache,
    load_prepared_configuration,
    resolve_analytics_store,
)
from src.services.v3_analytics_read import DashboardRead
from src.services.v3_analytics_refresh import (
    ANALYTICS_STALE_AFTER_SEC,
    MANUAL_REFRESH_COOLDOWN_SEC,
    V3AnalyticsRefreshService,
    apply_contour_filter_to_payload,
    build_refresh_service,
    read_dashboard,
)
from src.ui.v3_analytics_okpd_funnel import (
    DEFAULT_PAGE_SIZE,
    INITIAL_OKPD_RENDER_LIMIT,
    render_categories_tab,
    render_compact_kpis,
    render_okpd_funnel_table,
    render_scenarios_medals_quality,
    render_secondary_44_223,
    render_subcategories_tab,
)
from src.ui.v3_analytics_page_sections import render_infra_banner
from src.ui.v3_analytics_wave1_panel import render_wave1_operational_panel
from src.ui.v3_analytics_premodel_panel import render_premodel_source_panel
from src.ui.v3_analytics_pipeline_funnel import render_pipeline_funnel

# Contracts
HIDDEN_SECTIONS_HEAVY_RENDER = False
PAGE_LOAD_WAITS_FOR_REFRESH = False
FULL_SNAPSHOT_IN_SESSION_STATE = False
SNAPSHOT_FILE_READS_PER_RERUN = 1
SNAPSHOT_JSON_PARSES_PER_RERUN = 1
DASHBOARD_READ_ACQUIRES_REFRESH_LOCK = False
N_PLUS_ONE_ANALYTICS_QUERIES = False
REFRESH_BLOCKS_DASHBOARD_READ = False

_PERF = os.environ.get("CRM_V3_ANALYTICS_PERF", "0") == "1"


def _fmt_ts(value: Optional[datetime]) -> str:
    if value is None:
        return "—"
    try:
        return value.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)


def _perf_mark(bucket: Dict[str, float], name: str, t0: float) -> float:
    now = time.perf_counter()
    bucket[name] = round((now - t0) * 1000, 1)
    return now


@st.cache_data(ttl=45, show_spinner=False)
def _cached_prepared_configuration() -> Dict[str, Any]:
    return load_prepared_configuration()


@st.cache_data(ttl=45, show_spinner=False)
def _cached_precutover_payload(generation_id: int, finished_iso: str) -> Dict[str, Any]:
    """One snapshot file read/parse per generation (TTL soft refresh)."""
    store = PreCutoverFileCache()
    return dict(store.load_dashboard_payload(generation_id) or {})


def _read_dashboard_once(store, cache_kind: str) -> DashboardRead:
    """Normal page path: ≤1 heavy snapshot parse; no refresh lock."""
    assert DASHBOARD_READ_ACQUIRES_REFRESH_LOCK is False
    assert PAGE_LOAD_WAITS_FOR_REFRESH is False
    if cache_kind == "PRECUTOVER_FILE" or isinstance(store, PreCutoverFileCache):
        if not store.schema_ready():
            return DashboardRead(ready=False, schema_ready=False, data={}, message="cache unavailable", s7_queries=0)
        current = store.get_current_complete()
        latest = store.get_latest_attempt()
        if current is None:
            msg = "Нет завершённого снимка аналитики. Нажмите «Обновить данные»."
            if latest and latest.status == "FAILED":
                msg = f"Нет успешного снимка. Последняя ошибка: {latest.error_summary}"
            return DashboardRead(
                ready=False,
                schema_ready=True,
                data={},
                last_refresh_status=latest.status if latest else "NONE",
                last_refresh_error=latest.error_summary if latest else None,
                message=msg,
                s7_queries=0,
            )
        finished = current.finished_at or current.started_at
        finished_iso = finished.isoformat() if finished else ""
        payload = _cached_precutover_payload(int(current.generation_id), finished_iso)
        age = None
        stale = False
        if finished is not None:
            fin = finished if finished.tzinfo else finished.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - fin).total_seconds()
            stale = age > ANALYTICS_STALE_AFTER_SEC
        last_status = "COMPLETE"
        last_err = None
        if latest and latest.generation_id != current.generation_id and latest.status == "FAILED":
            last_status = "FAILED"
            last_err = latest.error_summary
        return DashboardRead(
            ready=True,
            schema_ready=True,
            data=payload,
            generation_id=current.generation_id,
            data_as_of=finished,
            last_refresh_status=last_status,
            last_refresh_error=last_err,
            stale=stale,
            snapshot_age_sec=age,
            message="",
            s7_queries=0,
        )
    # Canonical path: single read_dashboard call (no lock)
    return read_dashboard(store, stale_after_sec=ANALYTICS_STALE_AFTER_SEC)


def _get_store(service):
    kind = st.session_state.get("v3_analytics_cache_kind")
    cached = st.session_state.get("v3_analytics_store")
    if cached is not None and kind:
        return cached, kind
    crm_db = getattr(service, "crm_db", None) if service else None
    store, kind = resolve_analytics_store(crm_db)
    st.session_state["v3_analytics_store"] = store
    st.session_state["v3_analytics_cache_kind"] = kind
    return store, kind


def assert_no_full_snapshot_in_session() -> None:
    assert FULL_SNAPSHOT_IN_SESSION_STATE is False
    for key, val in list(st.session_state.items()):
        if key in ("v3_analytics_store", "service", "v3_refresh_engine"):
            continue
        if isinstance(val, dict) and ("okpd_funnel" in val or "subcategory_registry" in val):
            raise AssertionError(f"full snapshot leaked into session_state[{key}]")


def render_v3_analytics_page(service) -> None:
    assert PAGE_LOAD_WAITS_FOR_REFRESH is False
    assert FULL_SNAPSHOT_IN_SESSION_STATE is False
    assert HIDDEN_SECTIONS_HEAVY_RENDER is False
    assert DASHBOARD_READ_ACQUIRES_REFRESH_LOCK is False
    assert N_PLUS_ONE_ANALYTICS_QUERIES is False
    assert REFRESH_BLOCKS_DASHBOARD_READ is False

    timings: Dict[str, float] = {}
    t = time.perf_counter()

    st.title("Воронка коммерческих возможностей")
    st.caption(
        "S7 SOURCE → S13 PROJECTED → OKPD → Qwen 7b routing → opportunities → "
        "Candidate Medal → documents → Confirmed. Snapshot-only (no S7 on rerun)."
    )

    store, cache_kind = _get_store(service)
    _render_refresh_bar(service, store, cache_kind)
    t = _perf_mark(timings, "refresh_bar_ms", t)

    view = _read_dashboard_once(store, cache_kind)
    t = _perf_mark(timings, "snapshot_read_ms", t)
    assert view.s7_queries == 0

    # Tiny UI meta only — never stash full snapshot
    st.session_state["v3_analytics_last_view"] = {
        "data_as_of": _fmt_ts(view.data_as_of),
        "ui_status": "STALE" if view.stale else "Актуально",
        "generation_id": view.generation_id,
    }
    assert_no_full_snapshot_in_session()

    data = view.data or {}
    prepared = _cached_prepared_configuration()
    t = _perf_mark(timings, "prepared_config_ms", t)

    render_infra_banner(
        cache_kind=cache_kind,
        canonical_ready=(cache_kind == "CANONICAL_S13_CRM"),
        data=data,
    )
    if not view.ready:
        st.caption(view.message or "Нет снимка — нажмите «Обновить данные».")

    filters = _render_filters(prepared)
    data = apply_contour_filter_to_payload(data, filters["contour"])
    t = _perf_mark(timings, "filters_ms", t)

    render_pipeline_funnel(data)
    render_premodel_source_panel()
    render_wave1_operational_panel(data)
    t = _perf_mark(timings, "pipeline_funnel_ms", t)

    render_compact_kpis(data)
    t = _perf_mark(timings, "kpi_ms", t)

    # Explicit section nav — only selected section runs heavy render
    section = st.radio(
        "Раздел",
        [
            "Воронка по OKPD",
            "Категории",
            "Подкатегории",
            "Сценарии",
            "Медали",
            "Качество",
        ],
        horizontal=True,
        key="v3_analytics_section",
    )

    if section == "Воронка по OKPD":
        render_okpd_funnel_table(
            data,
            contour=filters["contour"],
            okpd_q=filters["okpd_q"],
            category=filters["category"],
        )
        render_secondary_44_223(data)
    elif section == "Категории":
        render_categories_tab(data, prepared)
    elif section == "Подкатегории":
        render_subcategories_tab(data)
    elif section in ("Сценарии", "Медали", "Качество"):
        render_scenarios_medals_quality(data)
    t = _perf_mark(timings, "section_ms", t)

    if _PERF:
        timings["total_page_build_ms"] = round(sum(v for k, v in timings.items() if k.endswith("_ms")), 1)
        st.caption("PERF " + " · ".join(f"{k}={v}" for k, v in timings.items()))
        st.caption(
            f"contracts: page_size_default={DEFAULT_PAGE_SIZE} "
            f"render_limit={INITIAL_OKPD_RENDER_LIMIT} "
            f"snapshot_reads≤{SNAPSHOT_FILE_READS_PER_RERUN}"
        )


def _render_refresh_bar(service, store, cache_kind: str) -> None:
    top = st.columns([3, 1, 2])
    view_hint = st.session_state.get("v3_analytics_last_view") or {}
    with top[0]:
        st.markdown(f"**Последнее обновление:** {view_hint.get('data_as_of') or '—'}")
    with top[1]:
        if st.button("Обновить данные", use_container_width=True):
            # Explicit click only — never on normal navigation
            engine = build_refresh_service(
                getattr(service, "tender_db", None),
                getattr(service, "crm_db", None),
                store=store,
                force_precutover=(cache_kind != "CANONICAL_S13_CRM"),
            )
            prev = st.session_state.get("v3_refresh_engine")
            if isinstance(prev, V3AnalyticsRefreshService):
                engine._last_manual_at = prev._last_manual_at
            result = engine.refresh_all(trigger="manual")
            st.session_state["v3_refresh_engine"] = engine
            if result.ok:
                _cached_precutover_payload.clear()
                st.session_state["v3_analytics_last_view"] = {
                    "data_as_of": _fmt_ts(datetime.now().astimezone()),
                    "ui_status": "Актуально",
                }
                st.success(result.message)
            else:
                st.warning(result.message)
            st.rerun()
    with top[2]:
        st.caption(f"Cooldown {MANUAL_REFRESH_COOLDOWN_SEC // 60} мин")


def _render_filters(prepared: Dict[str, Any]) -> Dict[str, str]:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        contour_label = st.selectbox("SOURCE", ["Все", "44-ФЗ", "223-ФЗ"], key="v3_a_contour")
    contour = {"Все": "ALL", "44-ФЗ": "44", "223-ФЗ": "223"}[contour_label]
    with c2:
        okpd_q = st.text_input("OKPD поиск", value="", key="v3_a_okpd_q")
    cats = ["Все категории"] + [
        c.get("category_code")
        for c in (prepared.get("category_coverage") or [])
        if c.get("category_code")
    ]
    with c3:
        cat = st.selectbox("CATEGORY", cats, key="v3_a_category")
    with c4:
        st.selectbox(
            "TRACK",
            ["Все", "Прямая поставка", "В составе работ", "Проектная потребность", "Проектное влияние"],
            key="v3_a_track",
        )
    with c5:
        st.selectbox(
            "MEDAL",
            ["Все", "Candidate Gold", "Candidate Silver", "Candidate Bronze", "Candidate Wood"],
            key="v3_a_medal",
        )
    with c6:
        st.selectbox(
            "LIFECYCLE",
            ["Все"] + [s.value for s in CommercialOpportunityState],
            key="v3_a_life",
        )
    return {
        "contour": contour,
        "okpd_q": okpd_q or "",
        "category": "ALL" if cat == "Все категории" else str(cat),
    }
