"""Compact one-line pipeline status for the queue-first first screen."""
from __future__ import annotations

from typing import Any, Dict

import streamlit as st

_CSS = """
<style>
.qf-pipeline {
    font-size: 12.5px; color: #0f172a; background: #f1f5f9;
    border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 6px 12px; margin: 2px 0 6px 0; line-height: 1.5;
}
.qf-pipeline .warn { color: #b45309; font-weight: 700; }
.qf-pipeline .bad  { color: #b91c1c; font-weight: 700; }
.qf-pipeline .ok   { color: #15803d; font-weight: 600; }
.qf-pipeline .sep  { color: #94a3b8; }
</style>
"""


def pipeline_line_text(data: Dict[str, Any]) -> str:
    if not data or not data.get("ok"):
        return "Конвейер: данные недоступны"
    parts = []
    hs = data.get("hours_since_intake")
    if hs is None:
        parts.append("Intake: н/д")
    elif hs >= 6:
        parts.append(f"Intake \u26a0 {int(hs)}ч без новых")
    else:
        parts.append(f"Intake {int(hs)}ч")

    o44, o223 = data.get("sync_open_44"), data.get("sync_open_223")
    if o44 is None and o223 is None:
        parts.append("Sync: н/д")
    else:
        parts.append(f"Sync: 44-ФЗ {o44 if o44 is not None else '?'} / 223-ФЗ {o223 if o223 is not None else '?'}")

    fa = data.get("feeder_admitted")
    parts.append(f"Feeder: +{fa}" if fa is not None else "Feeder: н/д")

    wb, wi = data.get("workers_busy"), data.get("workers_idle")
    parts.append(f"Workers: {wb} busy / {wi} idle" if wb is not None else "Workers: н/д")

    qp = data.get("queue_pending")
    parts.append(f"Queue: {qp} pending" if qp is not None else "Queue: н/д")

    cpu = data.get("cpu_pct")
    parts.append(f"S13 CPU {round(cpu)}%" if cpu is not None else "S13 CPU н/д")
    ol = data.get("ollama_pct")
    parts.append(f"Ollama {round(ol)}%" if ol is not None else "Ollama н/д")
    return "Конвейер: " + " · ".join(parts)


def render_pipeline_line(data: Dict[str, Any], *, qsvc_used: bool = False) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    text = pipeline_line_text(data)
    warn = ""
    if data.get("ok") and (data.get("hours_since_intake") or 0) >= 6:
        warn = "warn"
    st.markdown(
        f'<div class="qf-pipeline"><span class="{warn}">{_esc(text)}</span></div>',
        unsafe_allow_html=True,
    )
    if st.button("Открыть конвейер →", key="qfirst_open_pipeline"):
        st.session_state.nav_page = "pipeline"
        st.rerun()


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
