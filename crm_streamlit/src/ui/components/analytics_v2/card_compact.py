"""Карточка закупки для списка — информативный вид с секциями."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.card_trust import (
    resolve_level, submission_status, fmt_price, fmt_date,
    STAGE_DESCRIPTION, days_left, workdays_left,
    calc_deadline_info, deadline_window_label, participant_source_label,
)

_CSS = """
<style>
.cc-card-topbar {
    display: flex; justify-content: space-between;
    align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 4px;
}
.cc-badge {
    display: inline-block; padding: 2px 12px; border-radius: 999px;
    font-size: 11px; font-weight: 700; letter-spacing: .04em;
}
.cc-status-chip { font-size: 11px; color: #888; white-space: nowrap; }
.cc-title {
    font-size: 14px; font-weight: 600; line-height: 1.4; color: #1e293b;
    margin: 4px 0 2px 0;
}
.cc-region { font-size: 12px; color: #64748b; margin-bottom: 6px; }
.cc-section {
    font-size: 9px; font-weight: 700; letter-spacing: .09em;
    color: #94a3b8; text-transform: uppercase; margin: 8px 0 3px 0;
}
.cc-participants { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; margin: 2px 0; }
.cc-p-ok   { color: #22c55e; }
.cc-p-no   { color: #f87171; }
.cc-p-unkn { color: #94a3b8; }
.cc-check  { font-size: 12px; color: #555; line-height: 1.6; }
.cc-deadline-ok   { font-size: 12px; color: #16a34a; }
.cc-deadline-warn { font-size: 12px; color: #d97706; font-weight: 600; }
.cc-deadline-crit { font-size: 12px; color: #dc2626; font-weight: 700; }
.cc-signal-kw {
    display: flex; flex-wrap: wrap; gap: 4px; margin: 3px 0;
}
.cc-kw {
    font-size: 10px; padding: 1px 7px; border-radius: 4px;
    background: #fef9c3; color: #92400e; border: 1px solid #fde68a;
}
.cc-score-line { font-size: 11px; color: #64748b; margin-top: 4px; }
.cc-stage-hint { font-size: 10px; color: #94a3b8; font-style: italic; margin-top: 2px; }
.cc-demotion {
    font-size: 11px; color: #dc2626; font-weight: 600;
    background: #fee2e2; border-radius: 4px; padding: 2px 8px;
    display: inline-block; margin-top: 3px;
}
</style>
"""


def render_compact_card(card: dict, idx: int, session_key: str = "selected_procurement_id") -> None:
    st.markdown(_CSS, unsafe_allow_html=True)

    level_label, color, bg, is_medal = resolve_level(card)
    category   = card.get("crm_category") or "—"
    stage      = card.get("processing_stage", "matches_found")
    award      = card.get("award_status", "submission_open")
    end_date   = card.get("end_date")
    price      = card.get("initial_price")
    signal     = card.get("signal_score") or card.get("match_score") or 0
    commercial = card.get("commercial_score")
    nmck       = fmt_price(price)
    region     = card.get("delivery_region") or "—"
    customer   = card.get("customer")
    contractor = card.get("contractor_name")
    keywords   = card.get("matched_keywords") or []

    # Статус
    status_icon, status_label, _ = submission_status(award, end_date)

    # Дедлайн
    dl = calc_deadline_info(card)
    wdays   = dl["workdays"]
    req     = dl["required_display"]
    ratio   = dl["ratio"]
    cap     = dl["cap_level"]
    window  = dl["window_label"]
    dl_score = dl["deadline_score"]

    # Был ли понижен уровень из-за дедлайна?
    if is_medal and commercial is not None:
        # Вычислим базовый уровень без дедлайна
        from src.ui.components.analytics_v2.card_trust import LEVEL_THRESHOLDS
        base = "Wood"
        for thr, medal, _, _ in LEVEL_THRESHOLDS:
            if commercial >= thr:
                base = medal
                break
        demoted = (base != level_label.replace(" ✓", "")) and is_medal
    else:
        base = None
        demoted = False

    is_selected = st.session_state.get(session_key) == card.get("id")

    with st.container(border=True):

        # ── Топ-бар ──
        medal_prefix = "🥇 " if is_medal else ""
        st.markdown(
            f'<div class="cc-card-topbar">'
            f'<span class="cc-badge" style="background:{bg};color:{color};">'
            f'{medal_prefix}{level_label} · {category}</span>'
            f'<span class="cc-status-chip">{status_icon} {status_label}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Понижение уровня
        if demoted and base:
            st.markdown(
                f'<span class="cc-demotion">▼ {base} → {level_label.replace(" ✓","")} '
                f'из-за срока · {wdays} из {req} раб.дн.</span>',
                unsafe_allow_html=True,
            )

        # ── Заголовок ──
        title = card.get("auction_name") or "—"
        st.markdown(f'<div class="cc-title">{title}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="cc-region">📍 {region} · {nmck}</div>', unsafe_allow_html=True)

        # ── СИГНАЛЫ / ТОВАРНАЯ ВОЗМОЖНОСТЬ ──
        if is_medal and commercial is not None:
            st.markdown('<div class="cc-section">Товарная возможность</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="cc-score-line">Коммерческий score: <b>{commercial}/100</b> · '
                f'Сигнальный балл: {signal}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown('<div class="cc-section">Поисковые сигналы</div>', unsafe_allow_html=True)
            if keywords:
                kw_html = "".join(f'<span class="cc-kw">{k}</span>' for k in keywords[:6])
                st.markdown(f'<div class="cc-signal-kw">{kw_html}</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="cc-score-line">Сигнальный балл: <b>{signal}</b> · категория ожидает проверки</div>',
                unsafe_allow_html=True,
            )

        # ── УЧАСТНИКИ ──
        st.markdown('<div class="cc-section">Участники</div>', unsafe_allow_html=True)
        cust_src  = card.get("customer_source")
        cust_conf = card.get("customer_confidence")
        cust_lbl  = participant_source_label(cust_src, cust_conf) if cust_src else (
            "реестр" if customer else "не определён"
        )
        p_html = '<div class="cc-participants">'
        p_html += (
            f'<span class="cc-p-ok">✓ Заказчик: {customer} [{cust_lbl}]</span>'
            if customer
            else '<span class="cc-p-unkn">· Заказчик: не определён</span>'
        )
        p_html += '<span class="cc-p-unkn">· Балансодержатель: —</span>'
        p_html += '<span class="cc-p-unkn">· Проектировщик: —</span>'
        p_html += (
            f'<span class="cc-p-ok">✓ Подрядчик: {contractor}</span>'
            if contractor
            else '<span class="cc-p-no">✗ Подрядчик: не выбран</span>'
        )
        p_html += '</div>'
        st.markdown(p_html, unsafe_allow_html=True)

        # ── ПРОВЕРКА ──
        st.markdown('<div class="cc-section">Проверка</div>', unsafe_allow_html=True)
        doc_status = "не загружены" if stage in ("raw", "matches_found") else "загружены"
        ai_status  = (
            "в очереди" if stage in ("raw", "documents_loaded", "matches_found")
            else ("завершён" if stage in ("ranked", "manager_confirmed") else "выполняется")
        )
        ev_count = card.get("evidence_count") or "—"
        st.markdown(
            f'<div class="cc-check">'
            f'Документы: {doc_status} · Evidence: {ev_count} · ИИ: {ai_status}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── ДЕДЛАЙН ──
        st.markdown('<div class="cc-section">Коммерческое окно</div>', unsafe_allow_html=True)
        if wdays is None:
            dl_html = '<span class="cc-deadline-ok">Дата не указана</span>'
        elif wdays <= 1:
            dl_html = (
                f'<span class="cc-deadline-crit">⏰ Осталось {wdays} раб.дн. из {req} · '
                f'окно закрыто · Deadline score: {dl_score}/10</span>'
            )
        elif ratio is not None and ratio < 0.60:
            dl_html = (
                f'<span class="cc-deadline-warn">⚠ {wdays} раб.дн. из {req} · {window} · '
                f'Deadline score: {dl_score}/10</span>'
            )
        else:
            dl_html = (
                f'<span class="cc-deadline-ok">✓ {wdays} раб.дн. · требуется {req} · '
                f'{window} · Deadline score: {dl_score}/10</span>'
            )
        st.markdown(dl_html, unsafe_allow_html=True)

        # ── Stage hint ──
        if not is_medal:
            st.markdown(
                f'<div class="cc-stage-hint">{STAGE_DESCRIPTION.get(stage, stage)}</div>',
                unsafe_allow_html=True,
            )

        # ── Кнопка ──
        btn_label = "✓ Скрыть детали" if is_selected else "Открыть карточку"
        if st.button(
            btn_label, key=f"cc_{session_key}_{idx}",
            use_container_width=True,
            type="primary" if is_selected else "secondary",
        ):
            if is_selected:
                st.session_state.pop(session_key, None)
            else:
                st.session_state[session_key] = card["id"]
            st.rerun()
