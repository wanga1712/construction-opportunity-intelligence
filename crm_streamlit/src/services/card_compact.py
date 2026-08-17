"""Карточка закупки для списка — inline tabs, единый effective assessment contract."""
from __future__ import annotations

import json
import streamlit as st
from datetime import date

from src.ui.components.analytics_v2.card_trust import (
    resolve_level, submission_status, fmt_price, fmt_date,
    STAGE_DESCRIPTION, days_left, workdays_left,
    calc_deadline_info, deadline_window_label, participant_source_label,
)
from src.ui.components.analytics_v2.card_tabs_history import render_history_tab
from src.ui.components.analytics_v2.card_tabs_medals import render_medals_tab
from src.ui.components.analytics_v2.card_tabs_ai import render_ai_tab
from src.services.effective_assessment import EffectiveAssessment

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
.cc-region { font-size: 12px; color: #64748b; margin-bottom: 4px; }
.cc-ai-meta { font-size: 11px; color: #475569; margin-bottom: 6px; line-height: 1.6; }
.cc-section {
    font-size: 9px; font-weight: 700; letter-spacing: .09em;
    color: #94a3b8; text-transform: uppercase; margin: 8px 0 3px 0;
}
.cc-participants { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; margin: 2px 0; }
.cc-p-ok   { color: #22c55e; }
.cc-p-no   { color: #f87171; }
.cc-p-unkn { color: #94a3b8; }
.cc-deadline-ok   { font-size: 12px; color: #16a34a; }
.cc-deadline-warn { font-size: 12px; color: #d97706; font-weight: 600; }
.cc-deadline-crit { font-size: 12px; color: #dc2626; font-weight: 700; }
</style>
"""

_MEDAL_EMOJI  = {"GOLD": "🥇 ", "SILVER": "🥈 ", "BRONZE": "🥉 ", "WOOD": "🪵 "}
_MEDAL_COLOR  = {
    "GOLD": "#d4a017", "SILVER": "#7c8da1",
    "BRONZE": "#b36b2c", "WOOD": "#8c6b4f",
}


def render_compact_card(
    card: dict,
    idx: int,
    session_key: str = "selected_procurement_id",
    effective: EffectiveAssessment | None = None,
) -> None:
    """Render one compact card.

    ``effective`` should be pre-computed by the caller via
    ``get_effective_business_assessments`` (bulk). If None, falls back to
    per-card load (slower, for backward compatibility only).
    """
    st.markdown(_CSS, unsafe_allow_html=True)

    crm_id = card.get("id")

    # ── Lazy fallback (single card, no bulk pre-load) ──────────────────────
    if effective is None:
        from src.services.db_bootstrap import connect_databases
        from src.services.effective_assessment import get_effective_business_assessments
        try:
            _, _, crm_db, _ = connect_databases()
            eff_map = get_effective_business_assessments([crm_id], crm_db)
            effective = eff_map.get(crm_id)
        except Exception:
            pass

    # Build a local crm_db handle for tab actions (writes)
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()

    ai_status = effective.ai_status if effective else "UNASSESSED"
    is_assessed = ai_status == "ASSESSED"

    # ── Card fields ────────────────────────────────────────────────────────
    stage    = card.get("processing_stage", "—")
    award    = card.get("award_status", "submission_open")
    end_date = card.get("end_date")
    price    = card.get("initial_price")
    nmck     = fmt_price(price)
    region   = card.get("delivery_region") or "—"
    customer = card.get("customer")
    contractor = card.get("contractor_name")

    status_icon, status_label, _ = submission_status(award, end_date)

    dl       = calc_deadline_info(card)
    wdays    = dl["workdays"]
    req      = dl["required_display"]
    ratio    = dl["ratio"]
    window   = dl["window_label"]
    dl_score = dl["deadline_score"]

    # ── Effective values (single source of truth) ──────────────────────────
    eff_route     = (effective.route_profile if effective else None) or "—"
    eff_obj       = (effective.object_type   if effective else None) or "—"
    eff_proc      = (effective.procurement_type if effective else None) or "—"
    eff_relevance = (effective.business_relevance if effective else "UNKNOWN")
    eff_medal     = (effective.best_candidate_level if effective else None)
    eff_score     = (effective.best_candidate_score if effective else None)
    eff_opps      = (effective.category_opportunities if effective else [])
    eff_confidence= (effective.confidence if effective else None)
    eff_reasons   = (effective.reasons if effective else "—") or "—"
    eff_research  = (effective.overall_research_action if effective else None) or "METADATA_ONLY"

    # ── Badge in topbar ────────────────────────────────────────────────────
    if ai_status == "UNASSESSED":
        badge_emoji, badge_label = "🔘 ", "AI НЕ ОЦЕНЕН"
        badge_color, badge_bg    = "#64748b", "#f1f5f9"
    elif ai_status == "INCOMPLETE":
        badge_emoji, badge_label = "⚠️ ", "AI НЕПОЛНЫЙ"
        badge_color, badge_bg    = "#d97706", "#fef3c7"
    elif ai_status == "FAILED":
        badge_emoji, badge_label = "❌ ", "AI ОШИБКА"
        badge_color, badge_bg    = "#dc2626", "#fee2e2"
    elif eff_relevance == "OUT_OF_PROFILE":
        badge_emoji, badge_label = "⛔ ", "НЕ НАШ ПРОФИЛЬ"
        badge_color, badge_bg    = "#dc2626", "#fee2e2"
    elif eff_medal:
        badge_emoji  = _MEDAL_EMOJI.get(eff_medal, "")
        badge_label  = eff_medal
        badge_color  = _MEDAL_COLOR.get(eff_medal, "#8c6b4f")
        badge_bg     = badge_color + "22"
    else:
        # ASSESSED but no category opportunities
        badge_emoji, badge_label = "—  ", "БЕЗ МЕДАЛИ"
        badge_color, badge_bg    = "#94a3b8", "#f1f5f9"

    # ── Render ─────────────────────────────────────────────────────────────
    with st.container(border=True):
        # Топ-бар
        st.markdown(
            f'<div class="cc-card-topbar">'
            f'<span class="cc-badge" style="background:{badge_bg};color:{badge_color};">'
            f'{badge_emoji}{badge_label} · {eff_route}</span>'
            f'<span class="cc-status-chip">{status_icon} {status_label}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Название + регион
        title = card.get("auction_name") or "—"
        st.markdown(f'<div class="cc-title">{title}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="cc-region">📍 {region} · {nmck}</div>',
            unsafe_allow_html=True,
        )

        # Краткая AI-строка
        ai_parts = [f"AI: <b>{ai_status}</b>"]
        if is_assessed:
            if eff_route != "—":
                ai_parts.append(f"Route: <b>{eff_route}</b>")
            if eff_obj != "—":
                ai_parts.append(f"Object: <b>{eff_obj}</b>")
            ai_parts.append(f"Scope: <b>{eff_relevance}</b>")
            if eff_medal:
                scr = f"{eff_score:.0f}" if eff_score is not None else "—"
                ai_parts.append(f"Medal: <b>{eff_medal}</b> ({scr})")
            if eff_confidence is not None:
                ai_parts.append(f"Conf: <b>{float(eff_confidence):.0%}</b>")
        else:
            ai_parts.append("Scope: <b>UNKNOWN</b>")

        st.markdown(
            '<div class="cc-ai-meta">' + " · ".join(ai_parts) + "</div>",
            unsafe_allow_html=True,
        )

        # ── ALWAYS-VISIBLE TABS ────────────────────────────────────────────
        t_overview, t_ai, t_medals, t_docs, t_history = st.tabs([
            "📋 ОБЗОР", "🤖 AI / КАТЕГОРИИ", "🏅 МЕДАЛИ", "📁 ДОКУМЕНТЫ", "📜 ИСТОРИЯ"
        ])

        # TAB: ОБЗОР ──────────────────────────────────────────────────────
        with t_overview:
            if ai_status in ("UNASSESSED", "INCOMPLETE", "FAILED"):
                if ai_status == "UNASSESSED":
                    st.info("🔘 AI-классификация ещё не выполнена.")
                elif ai_status == "INCOMPLETE":
                    st.warning("⚠️ AI-оценка неполная / результат не сохранён.")
                else:
                    st.error("❌ Ошибка выполнения AI-оценки.")
            else:
                # Classification block
                st.markdown('<div class="cc-section">Классификация объекта</div>', unsafe_allow_html=True)
                rows = []
                if eff_route != "—":
                    rows.append(f"**Route:** `{eff_route}`")
                if eff_obj != "—":
                    rows.append(f"**Object type:** `{eff_obj}`")
                if eff_proc != "—":
                    rows.append(f"**Procurement type:** `{eff_proc}`")
                st.markdown("  \n".join(rows) if rows else "—")

                # Commercial assessment
                st.markdown('<div class="cc-section">Коммерческая оценка</div>', unsafe_allow_html=True)
                best_cat   = (effective.best_opportunity_category if effective else None) or "—"
                score_disp = f"{eff_score:.0f}/100" if eff_score is not None else "—"
                conf_disp  = f"{float(eff_confidence):.0%}" if eff_confidence is not None else "—"
                st.markdown(
                    f"**Scope:** `{eff_relevance}`  \n"
                    f"**Best category:** `{best_cat}`  \n"
                    f"**Medal:** `{eff_medal or '—'}`  \n"
                    f"**Score:** `{score_disp}`  \n"
                    f"**Confidence:** `{conf_disp}`"
                )

                if eff_reasons and eff_reasons != "—":
                    st.markdown('<div class="cc-section">Причины AI</div>', unsafe_allow_html=True)
                    st.caption(eff_reasons[:400])

            # Участники — always shown
            st.markdown('<div class="cc-section">Участники</div>', unsafe_allow_html=True)
            cust_src  = card.get("customer_source")
            cust_conf = card.get("customer_confidence")
            cust_lbl  = participant_source_label(cust_src, cust_conf) if cust_src else (
                "реестр" if customer else "не определён"
            )
            p_html  = '<div class="cc-participants">'
            p_html += (
                f'<span class="cc-p-ok">✓ Заказчик: {customer} [{cust_lbl}]</span>'
                if customer
                else '<span class="cc-p-unkn">· Заказчик: не определён</span>'
            )
            p_html += (
                f'<span class="cc-p-ok">✓ Подрядчик: {contractor}</span>'
                if contractor
                else '<span class="cc-p-no">✗ Подрядчик: не выбран</span>'
            )
            p_html += "</div>"
            st.markdown(p_html, unsafe_allow_html=True)

            # Коммерческое окно
            st.markdown('<div class="cc-section">Коммерческое окно</div>', unsafe_allow_html=True)
            if wdays is None:
                dl_html = '<span class="cc-deadline-ok">Дата не указана</span>'
            elif wdays <= 1:
                dl_html = (
                    f'<span class="cc-deadline-crit">⏰ {wdays} раб.дн. из {req} · '
                    f'окно закрыто · score: {dl_score}/10</span>'
                )
            elif ratio is not None and ratio < 0.60:
                dl_html = (
                    f'<span class="cc-deadline-warn">⚠ {wdays} раб.дн. из {req} · {window} · '
                    f'score: {dl_score}/10</span>'
                )
            else:
                dl_html = (
                    f'<span class="cc-deadline-ok">✓ {wdays} раб.дн. · требуется {req} · '
                    f'{window} · score: {dl_score}/10</span>'
                )
            st.markdown(dl_html, unsafe_allow_html=True)

        # TAB: AI / КАТЕГОРИИ ─────────────────────────────────────────────
        with t_ai:
            render_ai_tab(
                crm_db, crm_id,
                eff_route, eff_obj, eff_proc,
                eff_reasons, eff_opps,
                ai_status=ai_status,
            )

        # TAB: МЕДАЛИ ─────────────────────────────────────────────────────
        with t_medals:
            render_medals_tab(
                crm_db, crm_id, eff_opps,
                ai_cand_medal=eff_medal,
                ai_cand_score=eff_score,
                ai_reasons=eff_reasons,
                ai_status=ai_status,
            )

        # TAB: ДОКУМЕНТЫ ──────────────────────────────────────────────────
        with t_docs:
            st.markdown("### 📁 Документы закупки")
            match_count = card.get("match_count") or 0
            ev_count    = card.get("evidence_count") or 0
            file_count  = card.get("file_count") or 0

            col_d1, col_d2, col_d3 = st.columns(3)
            col_d1.metric("Файлов", file_count)
            col_d2.metric("Matches", match_count)
            col_d3.metric("Evidence", ev_count)

            st.markdown(
                f"**Статус:** `{stage}`  \n"
                f"**Research action:** `{eff_research}`"
            )

            if eff_opps:
                st.markdown("#### Действия по категориям:")
                for opp in eff_opps:
                    cat = opp.get("category_code") or "—"
                    act = opp.get("research_action") or "—"
                    st.markdown(f"- **{cat}** → `{act}`")
            else:
                if ai_status == "UNASSESSED":
                    st.caption("AI-классификация ещё не выполнена — категории недоступны.")
                else:
                    st.caption("Категории не определены.")

        # TAB: ИСТОРИЯ ────────────────────────────────────────────────────
        with t_history:
            render_history_tab(crm_db, crm_id)
