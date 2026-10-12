"""Cheap queue-first card + lazy detail rendering.

The card renders only fields that already travelled with the bounded page
query. Documents, AI payload, history and expert annotation load only after an
explicit click.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict

import streamlit as st

MEDAL_EMOJI = {"GOLD": "🥇", "SILVER": "🥈", "BRONZE": "🥉", "WOOD": "🪵"}
MEDAL_COLOR = {
    "GOLD": "#d4a017",
    "SILVER": "#7c8da1",
    "BRONZE": "#b36b2c",
    "WOOD": "#8c6b4f",
}
LAYER_LABEL = {
    "CONFIRMED": "Подтверждено документами",
    "PRELIMINARY": "Предварительно квалифицировано",
    "NONE": "Без меди",
}
RESEARCH_ICON = {
    "PRE_RESEARCH_WAITING": "⏳",
    "PENDING": "⏳",
    "PROCESSING": "🔄",
    "RUNNING": "🔄",
    "COMPLETED": "✅",
    "FAILED": "⛔",
    "NO_LINKS": "🔗",
}

_CSS = """
<style>
.qf-card { font-family: inherit; }
.qf-top { display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; align-items:center; }
.qf-medal { display:inline-block; padding:1px 10px; border-radius:999px; font-size:12px; font-weight:700; }
.qf-chip { font-size:11px; color:#64748b; white-space:nowrap; }
.qf-title { font-size:15px; font-weight:600; color:#1e293b; margin:6px 0 2px 0; line-height:1.35; }
.qf-cats { font-size:12px; color:#475569; margin:2px 0; }
.qf-meta { font-size:12px; color:#64748b; margin:2px 0; }
.qf-why { font-size:12px; color:#334155; margin-top:4px; }
.qf-state-ok { color:#15803d; font-weight:600; }
.qf-state-work { color:#b45309; font-weight:600; }
.qf-state-bad { color:#b91c1c; font-weight:600; }
</style>
"""


def _money(value: Any) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _days(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        return None
    return (value - date.today()).days


def _state_class(state: str) -> str:
    if state in ("FAILED", "NO_LINKS"):
        return "qf-state-bad"
    if state in ("COMPLETED",):
        return "qf-state-ok"
    return "qf-state-work"


def timeline_text(card) -> str:
    """Timeline/runway text for the card, from persisted dates only."""
    if card.lifecycle == "AWARDED":
        d = _days(card.execution_end_at) if card.execution_end_at else _days(card.end_date)
        if d is None:
            return "execution runway: н/д"
        return f"execution runway {d} дн." if d >= 0 else f"execution завершён {abs(d)} дн. назад"
    if card.lifecycle == "OPEN":
        d = _days(card.end_date)
        if d is None:
            return "срок торгов н/д"
        return f"до окончания торгов {d} дн." if d >= 0 else "срок торгов истёк"
    return "lifecycle н/д"


def render_queue_card(card, *, index: int, key_prefix: str) -> None:
    """Render one cheap card. Returns nothing; the open button is handled by caller."""
    st.markdown(_CSS, unsafe_allow_html=True)
    medal = card.medal or "—"
    color = MEDAL_COLOR.get(card.medal or "", "#94a3b8")
    emoji = MEDAL_EMOJI.get(card.medal or "", "—")
    cats = " · ".join(card.categories) if card.categories else "категории не найдены"

    with st.container(border=True):
        st.markdown(
            f'<div class="qf-card"><div class="qf-top">'
            f'<span class="qf-medal" style="background:{color}22;color:{color};">{emoji} {medal}'
            f' <span style="font-weight:400;font-size:11px;">· {LAYER_LABEL.get(card.medal_layer, "")}</span></span>'
            f'<span class="qf-chip">#{index} · id {card.procurement_id} · '
            f'{card.lifecycle} · {card.scope_label}</span>'
            f'</div>'
            f'<div class="qf-title">{_esc(card.title or "—")}</div>'
            f'<div class="qf-cats">{_esc(cats)}</div>'
            f'<div class="qf-meta">НМЦК: <b>{_money(card.nmck)}</b>'
            + (
                f" · контракт: <b>{_money(card.contract_price)}</b>"
                if card.lifecycle == "AWARDED" and card.contract_price
                else ""
            )
            + f" · {_esc(timeline_text(card))}</div>"
            f'<div class="qf-meta">🏢 {_esc(card.customer or "—")} · 📍 {_esc(card.region or "—")}</div>'
            f'<div class="qf-meta">Исследование: '
            f'<span class="{_state_class(card.research_state)}">'
            f'{RESEARCH_ICON.get(card.research_state, "•")} {_esc(card.research_state_label)}</span>'
            f' · Приоритет: <b>{card.priority if card.priority is not None else "—"}</b></div>'
            f'<div class="qf-why">Почему сейчас: {_esc(card.why_now or "—")}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button("Открыть карточку", key=f"{key_prefix}_open_{card.procurement_id}"):
            st.session_state.qfirst_open_id = card.procurement_id
            st.rerun()


def _esc(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_card_detail(card, detail: Dict[str, Any]) -> None:
    """Lazy detail: procurement fields + current opportunities (no documents/AI)."""
    procurement = detail.get("procurement") or {}
    authority = detail.get("authority") or {}
    opportunities = detail.get("opportunities") or []

    st.markdown(f"#### {card.title or '—'}")
    a, b, c = st.columns(3)
    a.metric("НМЦК", _money(procurement.get("initial_price") or card.nmck))
    b.metric("Цена контракта", _money(procurement.get("final_contract_price") or procurement.get("final_price")))
    c.metric("Приоритет", card.priority if card.priority is not None else "—")

    st.markdown(
        f"**Ссылка на закупку:** {procurement.get('tender_link') or '—'}  \n"
        f"**Заказчик:** {procurement.get('customer') or '—'}  \n"
        f"**Регион:** {procurement.get('delivery_region') or '—'}  \n"
        f"**Lifecycle:** `{authority.get('source_lifecycle') or card.lifecycle}` · "
        f"**Scope:** `{authority.get('procurement_scope_type') or card.scope_type}` · "
        f"**Admission:** `{authority.get('admission_state')}` / "
        f"`{authority.get('admission_policy_version')}`  \n"
        f"**Окно:** {timeline_text(card)}"
    )

    if opportunities:
        st.markdown("**Текущие коммерческие возможности (CURRENT):**")
        for o in opportunities:
            st.markdown(
                f"- `{o.get('commercial_category_code')}`"
                f" / `{o.get('commercial_subcategory_code') or '—'}` — "
                f"медаль **{o.get('current_effective_medal') or o.get('candidate_medal') or '—'}**"
                f" (candidate {o.get('candidate_initial_medal') or o.get('candidate_medal') or '—'}"
                f" → confirmed {o.get('confirmed_base_medal') or '—'})"
                f" · priority {o.get('commercial_priority_score') or '—'}"
                f" · {o.get('current_effective_reason') or o.get('commercial_state') or ''}"
            )
    else:
        st.caption(
            "CURRENT коммерческих возможностей нет — карточка показывает предварительную "
            "квалификацию из очереди документов."
        )
