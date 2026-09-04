"""Read-only UI components for OKPD Research Priority shadow predictions.

Contract:
- User-facing title: 'Приоритет исследования'
- Displays band (GOLD / SILVER / BRONZE / WOOD) and P(RESEARCH_HIT)
- Status badge: 'Теневой режим'
- Tooltip explanation: 'Прогноз показывает вероятность того, что после полного анализа документов будет найден хотя бы один подтвержденный целевой факт. Пока прогноз не влияет на скачивание и обработку закупки.'
- Strictly read-only; never mutates queue, priority, or backend state.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import streamlit as st

from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.repositories.okpd_prediction_repository import OKPDPriorPredictionRepository

_REPO = OKPDPriorPredictionRepository()

_BAND_ICONS = {
    "GOLD": "🥇",
    "SILVER": "🥈",
    "BRONZE": "🥉",
    "WOOD": "🪵",
}

_BAND_COLORS = {
    "GOLD": ("#d4a017", "#fef9c3", "#854d0e"),
    "SILVER": ("#64748b", "#f1f5f9", "#334155"),
    "BRONZE": ("#b45309", "#ffedd5", "#78350f"),
    "WOOD": ("#78350f", "#fef3c7", "#451a03"),
}

SHADOW_HELP_TEXT = (
    "Прогноз показывает вероятность того, что после полного анализа документов "
    "будет найден хотя бы один подтвержденный целевой факт. Пока прогноз не влияет "
    "на скачивание и обработку закупки."
)


def render_okpd_priority_card_block(
    procurement_id: int,
    okpd_code: Optional[str] = None,
) -> None:
    """Renders the standard read-only OKPD Research Priority block in a card."""
    st.markdown('<div class="crm-section-label">Приоритет исследования</div>', unsafe_allow_html=True)

    pred = _REPO.get_by_procurement_id(procurement_id, okpd_code)

    if not pred or pred.okpd_code_raw is None:
        st.caption("Нет прогноза · OKPD не указан")
        return

    band = pred.priority_band.upper()
    icon = _BAND_ICONS.get(band, "🏷️")
    border_col, bg_col, text_col = _BAND_COLORS.get(band, ("#94a3b8", "#f8fafc", "#1e293b"))
    p_pct = pred.p_research_hit * 100.0

    h = parse_okpd_hierarchy(pred.okpd_code_raw)
    signal_chain = h.format_signal_chain()

    html = f"""
    <div style="
        background: {bg_col};
        border: 1px solid {border_col};
        border-radius: 8px;
        padding: 12px 16px;
        margin: 8px 0;
        font-family: inherit;
    ">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="font-size: 15px; font-weight: 700; color: {text_col};">
                {icon} {band} · Вероятность полезной находки: {p_pct:.1f}%
            </div>
            <span style="
                background: #e2e8f0;
                color: #475569;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
                border-radius: 12px;
            " title="{SHADOW_HELP_TEXT}">Теневой режим · Пока не влияет на очередь ℹ️</span>
        </div>
        <div style="font-size: 12px; color: #475569; line-height: 1.5;">
            <div><b>OKPD:</b> {pred.okpd_code_raw}</div>
            <div><b>Сигнал:</b> {signal_chain}</div>
            <div><b>Модель:</b> OKPD Prior V1</div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
    st.caption(f"💡 {SHADOW_HELP_TEXT}")


def get_okpd_priority_compact_badge(
    procurement_id: int,
    okpd_code: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Returns compact priority representation for list view and sorting."""
    pred = _REPO.get_by_procurement_id(procurement_id, okpd_code)
    if not pred or pred.okpd_code_raw is None:
        return None

    band = pred.priority_band.upper()
    icon = _BAND_ICONS.get(band, "")
    p_pct = pred.p_research_hit * 100.0

    return {
        "band": band,
        "p_research_hit": pred.p_research_hit,
        "priority_percentile": pred.priority_percentile,
        "pct_str": f"{p_pct:.1f}%",
        "display_text": f"{icon} {band} ({p_pct:.1f}%)",
    }
