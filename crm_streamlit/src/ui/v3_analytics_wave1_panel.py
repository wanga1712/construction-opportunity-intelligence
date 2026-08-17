"""Wave-1 operational panel for Analytics V3 first tab.

All counters must come from the same reconciled Wave-1 payload
(`/var/lib/crm-v3-canary/wave1_7b_business_reconciliation_report.json`
via analytics cache `wave1` key).
"""
from __future__ import annotations

from typing import Any, Dict

import streamlit as st


def render_wave1_operational_panel(data: Dict[str, Any]) -> None:
    wave1 = data.get("wave1") or {}
    if not wave1:
        dash = data.get("dashboard") or {}
        wave1 = dash.get("wave1") or {}
    if not wave1:
        st.info("Wave-1 operational snapshot not yet in analytics cache.")
        return

    st.markdown("### Wave-1 reconciled (7B accepted)")
    st.caption(
        "ACTIVE MODEL: qwen2.5:7b · Assessment REVIEW ≠ opportunity review-flag. "
        "Tracks include UNKNOWN / NO_COMMERCIAL_ENTRY / NULL when present."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Wave total", wave1.get("WAVE1_MANIFEST_SIZE") or wave1.get("WAVE_ROWS_ACCOUNTED") or 100)
    c2.metric("Routed", wave1.get("ROUTED") or wave1.get("WAVE1_7B_ROUTED"))
    c3.metric("Review", wave1.get("REVIEW") or wave1.get("WAVE1_7B_REVIEW") or wave1.get("ASSESSMENT_REVIEW_COUNT"))
    c4.metric("Failed", wave1.get("FAILED") or wave1.get("WAVE1_7B_FAILED"))

    o1, o2, o3, o4 = st.columns(4)
    o1.metric("Opportunities", wave1.get("TOTAL_COMMERCIAL_OPPORTUNITIES"))
    o2.metric("From ROUTED", wave1.get("OPPORTUNITIES_FROM_ROUTED"))
    o3.metric("From REVIEW", wave1.get("OPPORTUNITIES_FROM_REVIEW"))
    o4.metric("From FAILED", wave1.get("OPPORTUNITIES_FROM_FAILED"))

    st.markdown("#### Candidate medals")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("GOLD", wave1.get("GOLD"))
    m2.metric("SILVER", wave1.get("SILVER"))
    m3.metric("BRONZE", wave1.get("BRONZE"))
    m4.metric("WOOD", wave1.get("WOOD"))
    st.caption(
        f"Assessment REVIEW={wave1.get('ASSESSMENT_REVIEW_COUNT')} · "
        f"Opportunity review flags={wave1.get('OPPORTUNITY_REVIEW_FLAG_COUNT')} — different concepts."
    )

    st.markdown("#### Tracks (complete)")
    t = wave1.get("OTHER_TRACKS") or {}
    cols = st.columns(6)
    cols[0].metric("DIRECT_SUPPLY", wave1.get("DIRECT_SUPPLY"))
    cols[1].metric("EMBEDDED_MATERIAL", wave1.get("EMBEDDED_MATERIAL"))
    cols[2].metric("DESIGN_REQUIREMENT", wave1.get("DESIGN_REQUIREMENT"))
    cols[3].metric("DESIGN_INFLUENCE", wave1.get("DESIGN_INFLUENCE"))
    cols[4].metric("UNKNOWN", t.get("UNKNOWN", 0))
    cols[5].metric(
        "OTHER",
        sum(v for k, v in t.items() if k != "UNKNOWN") if isinstance(t, dict) else 0,
    )
    if t:
        st.write("other_tracks", t)

    st.markdown("#### Research decisions")
    rcols = st.columns(4)
    rcols[0].metric("ACTIVE_RESEARCH", wave1.get("ACTIVE_RESEARCH") or wave1.get("ACTIVE_RESEARCH_QUEUE"))
    rcols[1].metric("DISCOVERY_REVIEW", wave1.get("DISCOVERY_REVIEW") or wave1.get("DISCOVERY_REVIEW_QUEUE"))
    rcols[2].metric("NO_RESEARCH_REQUIRED", wave1.get("NO_RESEARCH_REQUIRED"))
    rcols[3].metric("EXECUTABLE_JOBS", wave1.get("EXECUTABLE_DOCUMENT_JOBS"))
    st.write(
        {
            "FOLLOW_UP_AWARDED": wave1.get("FOLLOW_UP_AWARDED") or wave1.get("FOLLOW_UP_AWARDED_QUEUE"),
            "HOLD_WAITING": wave1.get("HOLD_WAITING"),
            "CLOSED_NO_RESEARCH": wave1.get("CLOSED_NO_RESEARCH"),
            "SUPPRESSED": wave1.get("SUPPRESSED"),
            "FAILED_NO_DECISION": wave1.get("FAILED_NO_DECISION"),
            "OTHER": wave1.get("OTHER_RESEARCH_STATE"),
            "document_job_reasons": wave1.get("document_job_reasons"),
        }
    )

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("AVG latency s", wave1.get("AVG_LATENCY"))
    p2.metric("P50", wave1.get("P50_LATENCY"))
    p3.metric("P95", wave1.get("P95_LATENCY"))
    p4.metric("objects/hour", wave1.get("PROCUREMENTS_PER_HOUR"))

    with st.expander("Row-level / top research", expanded=False):
        top = (wave1.get("top_active_research") or [])[:20]
        if top:
            st.dataframe(top, use_container_width=True, hide_index=True)
        st.caption("Full rows: /var/lib/crm-v3-canary/wave1_7b_reconciliation_rows.csv")

    with st.expander("Category distribution", expanded=False):
        st.write("by_category_opportunities", wave1.get("by_category_opportunities") or {})
        st.write("by_category_unique_procurements", wave1.get("by_category_unique_procurements") or {})
        st.write("multi_category_ids", wave1.get("MULTI_CATEGORY_PROCUREMENT_IDS") or [])
