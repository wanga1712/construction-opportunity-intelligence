"""Streamlit sections for V3 analytics — always render structure."""
from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from src.domain.commercial_routing_v3 import OpportunityTrack
from src.services.v3_analytics_metric_state import (
    MetricState,
    confirmed_metric_state,
    medal_text,
    metric_display,
    routing_metric_state,
)
from src.services.v3_analytics_service import TRACK_LABELS_RU


def render_infra_banner(*, cache_kind: str, canonical_ready: bool, data: Dict[str, Any]) -> None:
    st.caption(
        f"V3 persistence: {'активна (S13 CRM cache)' if canonical_ready else 'ожидает миграцию S13 CRM'} · "
        f"Source analytics: {'активна' if data else 'нет снимка'} · "
        f"Routing: остановлен · Documents: остановлены · "
        f"Cache: {cache_kind}"
    )


def render_top_kpis(data: Dict[str, Any]) -> None:
    src = int(data.get("source_open") or 0)
    target = int(data.get("target_v3_eligible_approx") or 0)
    crm = int(data.get("crm_projected") or 0)
    level_b = bool(data.get("level_b_ready"))
    has_routing = int(data.get("routed_procurements") or 0) > 0 or int(data.get("total_opportunities") or 0) > 0
    r_state = routing_metric_state(level_b, has_routing)

    specs = [
        ("Получено из S7", str(src), "LIVE"),
        ("Target V3 projection", str(target), "LIVE"),
        ("Текущая CRM", str(crm), "LIVE"),
        ("Routing", metric_display(None, r_state, not_started_hint="Routing ещё не выполнялся")[0], "NOT STARTED"),
        (
            "Commercial opportunities",
            metric_display(None, r_state, not_started_hint="Routing ещё не выполнялся")[0],
            "NOT STARTED",
        ),
        (
            "Candidate Gold",
            metric_display(None, r_state, not_started_hint="Routing ещё не выполнялся")[0],
            "NOT STARTED",
        ),
    ]
    if r_state == MetricState.VALUE:
        specs[3] = ("Routing", str(data.get("routed_procurements") or 0), "LIVE")
        specs[4] = ("Commercial opportunities", str(data.get("total_opportunities") or 0), "LIVE")
        g = data.get("candidate_gold")
        specs[5] = ("Candidate Gold", str(g) if g is not None else "0", "LIVE")

    cols = st.columns(6)
    for col, (title, value, badge) in zip(cols, specs):
        with col:
            st.metric(title, value)
            st.caption(badge)


def render_funnel(data: Dict[str, Any]) -> None:
    st.markdown("##### Воронка")
    level_b = bool(data.get("level_b_ready"))
    has_routing = int(data.get("routed_procurements") or 0) > 0 or int(data.get("total_opportunities") or 0) > 0
    r_state = routing_metric_state(level_b, has_routing)
    c_state = confirmed_metric_state(bool(data.get("level_c_ready")))
    steps = [
        ("S7", str(data.get("source_open") or 0), "LIVE"),
        ("Technical eligibility", str(data.get("target_v3_eligible_approx") or 0), "LIVE"),
        ("CRM projection", str(data.get("crm_projected") or 0), "LIVE"),
        ("Routing", metric_display(None, r_state)[0], "NOT STARTED" if r_state != MetricState.VALUE else "LIVE"),
        (
            "Opportunities",
            metric_display(None, r_state)[0],
            "NOT STARTED" if r_state != MetricState.VALUE else "LIVE",
        ),
        (
            "Candidate Gold",
            metric_display(None, r_state, not_started_hint="Ожидает routing")[0],
            "NOT STARTED" if r_state != MetricState.VALUE else "LIVE",
        ),
        (
            "Confirmed Gold",
            metric_display(None, c_state, not_available_hint="Ожидает documents")[0],
            "PENDING DOCS",
        ),
    ]
    if r_state == MetricState.VALUE:
        steps[3] = ("Routing", str(data.get("routed_procurements") or 0), "LIVE")
        steps[4] = ("Opportunities", str(data.get("total_opportunities") or 0), "LIVE")
        steps[5] = ("Candidate Gold", str(data.get("candidate_gold") if data.get("candidate_gold") is not None else 0), "LIVE")
    cols = st.columns(len(steps))
    for col, (name, val, badge) in zip(cols, steps):
        with col:
            st.markdown(f"**{name}**")
            st.write(val)
            st.caption(badge)


def render_source_44_223(data: Dict[str, Any]) -> None:
    st.markdown("##### 44 / 223")
    c1, c2 = st.columns(2)
    with c1:
        st.write(
            f"**44-ФЗ** OPEN: **{data.get('source_44_open', 0)}** · "
            f"WAITING: **{data.get('source_44_waiting', 0)}**"
        )
    with c2:
        st.write(
            f"**223-ФЗ** OPEN: **{data.get('source_223_open', 0)}** · "
            f"WAITING: **{data.get('source_223_waiting', 0)}**"
        )


def render_projection_block(data: Dict[str, Any]) -> None:
    st.markdown("##### Projection")
    src_el = int(data.get("target_v3_eligible_approx") or 0)
    target = src_el
    current = int(data.get("crm_projected") or 0)
    delta = max(0, target - current)
    awarded = int(data.get("awarded_history_excluded") or 0)
    st.write(
        f"SOURCE ELIGIBLE: **{src_el}** · TARGET V3 PROJECTION: **{target}** · "
        f"CURRENT CRM: **{current}** · DELTA: **{delta}**"
    )
    st.caption(
        f"FULL HISTORICAL AWARDED EXCLUDED: **{awarded}** · "
        "LEGACY ORPHANS PRESERVED: policy active (not dumped)"
    )


def render_prepared_config(prepared: Dict[str, Any]) -> None:
    st.markdown("##### Configuration readiness (PREPARED / NOT DEPLOYED)")
    st.caption(prepared.get("label") or "PREPARED / NOT YET DEPLOYED TO V3 DB")
    st.write(
        f"COMMERCIAL TAXONOMY: **{prepared.get('commercial_taxonomy', 'prepared')}** · "
        f"OKPD PRIORS: **{prepared.get('okpd_priors_prepared', '—')}** prepared · "
        f"categories with priors: **{prepared.get('categories_with_priors', '—')}** · "
        f"LEGACY STOP SIGNALS: **{prepared.get('legacy_soft_negatives', '—')}** soft negative"
    )
    without = prepared.get("categories_without_priors") or []
    if without:
        st.caption("Without priors: " + ", ".join(str(x) for x in without))


def render_scenario_cards(data: Dict[str, Any]) -> None:
    st.markdown("##### Сценарии")
    level_b = bool(data.get("level_b_ready"))
    has_routing = int(data.get("total_opportunities") or 0) > 0
    state = routing_metric_state(level_b, has_routing)
    tracks = data.get("tracks") or {}
    cols = st.columns(4)
    keys = (
        OpportunityTrack.DIRECT_SUPPLY.value,
        OpportunityTrack.EMBEDDED_MATERIAL.value,
        OpportunityTrack.DESIGN_REQUIREMENT.value,
        OpportunityTrack.DESIGN_INFLUENCE.value,
    )
    for col, key in zip(cols, keys):
        with col:
            st.markdown(f"**{TRACK_LABELS_RU.get(key, key)}**")
            if state == MetricState.VALUE:
                t = tracks.get(key) or {}
                st.write(f"Закупки: {t.get('procurements', 0)}")
                st.write(f"Возможности: {t.get('opportunities', 0)}")
                st.write(f"Gold: {t.get('GOLD', 0)}")
            else:
                st.write(metric_display(None, MetricState.NOT_STARTED)[0])
                st.caption("NOT STARTED")


def render_category_table(data: Dict[str, Any], prepared: Dict[str, Any]) -> None:
    st.markdown("##### Категории")
    coverage = prepared.get("category_coverage") or []
    rows: List[Dict[str, Any]] = []
    level_b = bool(data.get("level_b_ready"))
    has_routing = int(data.get("total_opportunities") or 0) > 0
    live_rows = {r.get("category"): r for r in (data.get("category_rows") or []) if r.get("category")}
    waiting = "— · Ожидает routing"
    for c in coverage:
        code = c.get("category_code")
        live = live_rows.get(code) if (level_b and has_routing) else None
        rows.append(
            {
                "CATEGORY": code,
                "REGISTRY": "prepared",
                "OKPD priors": c.get("total_okpd_priors", 0),
                "Matcher terms": "—",
                "Routing signals": int(c.get("positive_signals") or 0)
                + int(c.get("negative_signals") or 0),
                "Direct": live.get("direct_supply") if live else waiting,
                "Embedded": live.get("embedded_material") if live else waiting,
                "Design": live.get("design_requirement") if live else waiting,
                "Candidate Gold": live.get("candidate_gold") if live else waiting,
            }
        )
    if not rows:
        st.info("Нет prepared category coverage в отчёте.")
        return
    st.dataframe(rows, hide_index=True, use_container_width=True)


def render_medal_blocks(data: Dict[str, Any]) -> None:
    st.markdown("##### Medals")
    level_b = bool(data.get("level_b_ready"))
    has_routing = int(data.get("total_opportunities") or 0) > 0
    r_state = routing_metric_state(level_b, has_routing)
    c_state = confirmed_metric_state(bool(data.get("level_c_ready")))
    left, right = st.columns(2)
    with left:
        st.markdown("**Candidate**")
        st.caption("Routing ещё не выполнялся." if r_state != MetricState.VALUE else "LIVE")
        for m in ("GOLD", "SILVER", "BRONZE", "WOOD"):
            label = medal_text(m, confirmed=False)
            if r_state == MetricState.VALUE:
                key = {"GOLD": "candidate_gold", "SILVER": "candidate_silver", "BRONZE": "candidate_bronze", "WOOD": "candidate_wood"}[m]
                st.write(f"{label}: **{data.get(key, 0)}**")
            else:
                st.write(f"{label}: {metric_display(None, MetricState.NOT_STARTED)[0]}")
    with right:
        st.markdown("**Confirmed**")
        st.caption("Document confirmation ещё не выполнялась.")
        for m in ("GOLD", "SILVER", "BRONZE", "WOOD"):
            st.write(f"{medal_text(m, confirmed=True)}: {metric_display(None, c_state)[0]}")


def render_lifecycle_discovery_quality(data: Dict[str, Any]) -> None:
    st.markdown("##### Lifecycle / Discovery / Quality / Versions")
    level_b = bool(data.get("level_b_ready"))
    has_routing = int(data.get("total_opportunities") or 0) > 0
    state = routing_metric_state(level_b, has_routing)
    if state != MetricState.VALUE:
        st.write(f"Lifecycle: {metric_display(None, MetricState.NOT_STARTED)[0]}")
        st.write(f"Discovery: {metric_display(None, MetricState.NOT_STARTED)[0]}")
    else:
        st.write(f"Active leads: **{data.get('active_leads', 0)}**")
        st.write(f"Discovery: **{data.get('discovery_required', 0)}**")
    st.write(f"OKPD priors runtime: **{data.get('okpd_priors_status', 'NOT_DEPLOYED')}**")
    vers = data.get("versions") or {}
    st.write(f"Version status: **{vers.get('status', 'V3 schema not active')}**")
    fails = data.get("failures") or {}
    if fails:
        st.caption("Failures: " + ", ".join(f"{k}={v}" for k, v in list(fails.items())[:6]))
