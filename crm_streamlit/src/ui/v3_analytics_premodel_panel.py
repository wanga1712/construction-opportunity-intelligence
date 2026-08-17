"""Pre-model Analytics V3 panel (no AI / no S7 on Streamlit rerun)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import streamlit as st

SNAP = Path("/var/lib/crm-v3-canary/canonical_card_premodel_gate1/analytics_premodel_snapshot.json")
CANARY = Path("/var/lib/crm-v3-canary/canonical_card_premodel_gate1/CANARY_V2_premodel_review.csv")


def _load() -> Dict[str, Any]:
    if not SNAP.exists():
        return {}
    try:
        return json.loads(SNAP.read_text(encoding="utf-8"))
    except Exception:
        return {}


def render_premodel_source_panel() -> None:
    data = _load()
    pre = data.get("premodel") or {}
    if not pre:
        st.info("Pre-model canonical-card snapshot not built yet.")
        return
    st.markdown("### Pre-model source foundation (CANARY_V2)")
    st.caption("Cached snapshot — no S7 query on rerun. NO model output.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Forward new", pre.get("FORWARD_NEW"))
    c2.metric("Backward recovered", pre.get("BACKWARD_RECOVERED"))
    c3.metric("RGK recovered", pre.get("RGK_RECOVERED"))
    c4.metric("Canary V2 size", pre.get("CANARY_V2_SIZE"))
    a1, a2, a3 = st.columns(3)
    a1.metric("ACTIVE (OPEN)", pre.get("ACTIVE"))
    a2.metric("WAITING", pre.get("WAITING"))
    a3.metric("AWARDED", pre.get("AWARDED"))
    p1, p2, p3 = st.columns(3)
    p1.metric("Commercial product prior links", pre.get("COMMERCIAL_PRODUCT_PRIOR_LINKS"))
    p2.metric("Contextual research prior links", pre.get("CONTEXTUAL_RESEARCH_PRIOR_LINKS"))
    cov = pre.get("DOCUMENT_LINK_COVERAGE") or {}
    p3.metric("Docs with links (canary)", cov.get("with"))
    ex = pre.get("deadline_examples") or {}
    st.write("Deadline pressure examples (5d vs 30d, 2d remaining)", ex)
    if CANARY.exists():
        st.caption(f"Review CSV: {CANARY}")
        with st.expander("CANARY_V2 preview (first 30 rows)", expanded=False):
            try:
                import pandas as pd

                df = pd.read_csv(CANARY)
                st.dataframe(df.head(30), use_container_width=True, hide_index=True)
            except Exception as exc:
                st.warning(str(exc))
