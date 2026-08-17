"""Sequential S7→Confirmed pipeline funnel UI for Analytics V3."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import streamlit as st

from src.services.v3_analytics_metric_state import MetricState, metric_display

_STAGE_ORDER: List[Tuple[str, str]] = [
    ("s7_source", "S7 SOURCE"),
    ("s13_projected", "S13 PROJECTED"),
    ("okpd_context", "OKPD CONTEXT"),
    ("qwen_routing", "QWEN ROUTING"),
    ("commercial_opportunities", "COMMERCIAL OPPORTUNITIES"),
    ("candidate_medal", "CANDIDATE MEDAL"),
    ("document_research", "DOCUMENT RESEARCH"),
    ("confirmed_medal", "CONFIRMED MEDAL"),
]


def _fmt_val(v: Any, state: str) -> str:
    if state in (MetricState.NOT_STARTED.value, MetricState.NOT_AVAILABLE.value, "NOT_STARTED", "NOT_AVAILABLE"):
        return metric_display(None, MetricState[state] if state in MetricState.__members__ else MetricState.NOT_STARTED)[0]
    if v is None:
        return metric_display(None, MetricState.NOT_STARTED)[0]
    return str(v)


def _headline_counts(key: str, block: Dict[str, Any]) -> str:
    if key == "s7_source":
        return (
            f"OPEN {block.get('S7_OPEN_TOTAL', 0)} · "
            f"WAITING {block.get('S7_WAITING_TOTAL', 0)} · "
            f"AWARDED_FULL {block.get('S7_AWARDED_FULL_HISTORY_TOTAL', 0)}"
        )
    if key == "s13_projected":
        return (
            f"OPEN {block.get('PROJECTED_OPEN', 0)} · "
            f"WAITING {block.get('PROJECTED_WAITING', 0)} · "
            f"AWARDED_ADMITTED {block.get('PROJECTED_AWARDED_RELEVANT', 0)} · "
            f"EXCLUDED {block.get('FULL_HISTORICAL_AWARDED_IGNORED', 0)}"
        )
    if key == "okpd_context":
        return (
            f"CONSTR {block.get('CONSTRUCTION_OKPD', 0)} · "
            f"PIR {block.get('DESIGN_PIR_OKPD', 0)} · "
            f"PC {block.get('COMPUTERS_OKPD', 0)} · "
            f"LIGHT {block.get('LIGHTING_OKPD', 0)} · "
            f"OTHER {block.get('OTHER_OKPD', 0)} · "
            f"MISS {block.get('MISSING_OKPD', 0)}"
        )
    if key == "qwen_routing":
        stt = block.get("state") or "NOT_STARTED"
        if stt != "VALUE":
            return _fmt_val(None, stt)
        return f"PENDING {block.get('PENDING_ROUTING', 0)} · DONE {block.get('ROUTING_COMPLETED', 0)}"
    stt = block.get("state") or "NOT_STARTED"
    if stt != "VALUE":
        return _fmt_val(None, stt)
    return "см. детали"


def render_pipeline_funnel(data: Dict[str, Any]) -> None:
    """Top-of-page sequential funnel; expandable stages; source badges."""
    funnel = data.get("pipeline_funnel") or {}
    st.markdown("### Воронка: Source → Confirmed")
    st.caption(
        "S7 SOURCE → S13 PROJECTED → OKPD CONTEXT → QWEN ROUTING → "
        "COMMERCIAL OPPORTUNITIES → CANDIDATE MEDAL → DOCUMENT RESEARCH → CONFIRMED MEDAL"
    )

    cols = st.columns(len(_STAGE_ORDER))
    for col, (key, title) in zip(cols, _STAGE_ORDER):
        block = funnel.get(key) or {}
        with col:
            st.markdown(f"**{title}**")
            st.write(_headline_counts(key, block))
            st.caption(block.get("badge") or "")

    for key, title in _STAGE_ORDER:
        block = funnel.get(key) or {}
        with st.expander(f"{title} · {block.get('badge') or ''}", expanded=(key in ("s7_source", "s13_projected"))):
            st.caption(block.get("explanation") or "")
            state = block.get("state")
            if key == "s7_source":
                st.markdown("**SOURCE TRUTH (S7 tender_monitor)** — не projection")
                st.write(f"S7_OPEN_TOTAL: **{block.get('S7_OPEN_TOTAL', 0)}**")
                st.write(f"S7_WAITING_TOTAL: **{block.get('S7_WAITING_TOTAL', 0)}**")
                st.write(f"S7_AWARDED_FULL_HISTORY_TOTAL: **{block.get('S7_AWARDED_FULL_HISTORY_TOTAL', 0)}**")
                b = block.get("by_44_223") or {}
                st.write(
                    f"44-ФЗ: open={b.get('open_44', 0)}, waiting={b.get('waiting_44', 0)}, "
                    f"awarded_full={b.get('awarded_44', 0)}"
                )
                st.write(
                    f"223-ФЗ: open={b.get('open_223', 0)}, waiting={b.get('waiting_223', 0)}, "
                    f"awarded_full={b.get('awarded_223', 0)}"
                )
            elif key == "s13_projected":
                st.markdown("**S13 crm — допущенные projection rows**")
                st.write(f"S13 открытые (PROJECTED_OPEN): **{block.get('PROJECTED_OPEN', 0)}**")
                st.write(f"S13 ожидание (PROJECTED_WAITING): **{block.get('PROJECTED_WAITING', 0)}**")
                st.write(
                    f"S13 разыгранные — допущены в CRM (PROJECTED_AWARDED_RELEVANT): "
                    f"**{block.get('PROJECTED_AWARDED_RELEVANT', 0)}**"
                )
                st.write(
                    f"S7 разыгранные — полная история vs excluded: "
                    f"FULL_HISTORICAL_AWARDED_IGNORED=**{block.get('FULL_HISTORICAL_AWARDED_IGNORED', 0)}**"
                )
                st.write(f"PROJECTED_TOTAL: **{block.get('PROJECTED_TOTAL', 0)}**")
            elif key == "okpd_context":
                for k in (
                    "CONSTRUCTION_OKPD",
                    "DESIGN_PIR_OKPD",
                    "COMPUTERS_OKPD",
                    "LIGHTING_OKPD",
                    "OTHER_OKPD",
                    "MISSING_OKPD",
                ):
                    st.write(f"{k}: **{block.get(k, 0)}**")
            elif key == "qwen_routing":
                st.write(f"Model: **{block.get('model', 'qwen2.5:7b')}**")
                st.write(f"State: **{state or 'NOT_STARTED'}**")
                for k in (
                    "PENDING_ROUTING",
                    "SENT_TO_MODEL",
                    "ROUTING_COMPLETED",
                    "ROUTING_FAILED",
                    "REVIEW_REQUIRED",
                    "UNKNOWN",
                ):
                    st.write(f"{k}: **{_fmt_val(block.get(k), state or 'NOT_STARTED')}**")
                st.caption("Legacy AI assessments excluded from V3 routing completion.")
            elif key == "commercial_opportunities":
                st.write(f"State: **{state or 'NOT_STARTED'}**")
                for k in ("CATEGORY_ASSIGNED", "SUBCATEGORY_ASSIGNED", "SUBCATEGORY_NOT_ASSIGNED"):
                    st.write(f"{k}: **{_fmt_val(block.get(k), state or 'NOT_STARTED')}**")
                tracks = block.get("tracks") or {}
                for t, v in tracks.items():
                    st.write(f"{t}: **{_fmt_val(v, state or 'NOT_STARTED')}**")
            elif key == "candidate_medal":
                st.write(f"State: **{state or 'NOT_STARTED'}**")
                st.caption("Runtime medal (no second model call).")
                for k in (
                    "CANDIDATE_GOLD",
                    "CANDIDATE_SILVER",
                    "CANDIDATE_BRONZE",
                    "CANDIDATE_NONE_REVIEW",
                ):
                    st.write(f"{k}: **{_fmt_val(block.get(k), state or 'NOT_STARTED')}**")
            elif key == "document_research":
                st.write("State: **NOT STARTED**")
                for k in (
                    "RESEARCH_ELIGIBLE",
                    "QUEUE_CREATED",
                    "DOCUMENTS_DISCOVERED",
                    "DOCUMENTS_DOWNLOADED",
                    "DOCUMENTS_PARSED",
                    "EVIDENCE_FOUND",
                ):
                    st.write(f"{k}: **{_fmt_val(None, 'NOT_STARTED')}**")
            elif key == "confirmed_medal":
                st.write("State: **NOT STARTED**")
                for k in (
                    "CONFIRMED_GOLD",
                    "CONFIRMED_SILVER",
                    "CONFIRMED_BRONZE",
                    "CONFIRMED_REJECTED",
                    "CONFIRMED_REVIEW",
                ):
                    st.write(f"{k}: **{_fmt_val(None, 'NOT_STARTED')}**")
