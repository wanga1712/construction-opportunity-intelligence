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

    # ── Human annotation state (primary truth) ───────────────────────────
    from src.services.expert_annotation_service import load_expert_annotation
    _expert = load_expert_annotation(crm_id, crm_db)
    _expert_payload = (_expert.get("annotation_payload") or _expert.get("payload") or {}) if _expert else {}
    _expert_scope = _expert_payload.get("expert_category_scope") if _expert_payload else None
    _expert_medal_val = _expert_payload.get("expert_medal") if _expert_payload else None
    _expert_cats = [
        o.get("category_code") for o in (_expert_payload.get("opportunities") or [])
        if isinstance(o, dict) and o.get("category_code")
    ] if _expert_payload else []

    # ── Badge in topbar ────────────────────────────────────────────────────
    if _expert_scope == "OUT_OF_CATEGORY":
        badge_emoji, badge_label = "⛔ ", "ВНЕ КАТЕГОРИЙ"
        badge_color, badge_bg    = "#dc2626", "#fee2e2"
    elif _expert_scope == "UNCERTAIN":
        badge_emoji, badge_label = "❓ ", "НЕ УВЕРЕН"
        badge_color, badge_bg    = "#d97706", "#fef3c7"
    elif _expert_scope == "IN_CATEGORY" and _expert_medal_val:
        badge_emoji  = _MEDAL_EMOJI.get(_expert_medal_val, "")
        badge_label  = _expert_medal_val
        badge_color  = _MEDAL_COLOR.get(_expert_medal_val, "#8c6b4f")
        badge_bg     = badge_color + "22"
    elif _expert_scope == "IN_CATEGORY":
        badge_emoji, badge_label = "✅ ", "В КАТЕГОРИИ"
        badge_color, badge_bg    = "#16a34a", "#dcfce7"
    elif _expert is not None:
        # Has annotation but no scope — legacy
        badge_emoji, badge_label = "📝 ", "РАЗМЕЧЕНО"
        badge_color, badge_bg    = "#2563eb", "#dbeafe"
    else:
        badge_emoji, badge_label = "🔘 ", "НЕ РАЗМЕЧЕНО"
        badge_color, badge_bg    = "#64748b", "#f1f5f9"

    # Source law label for topbar
    from src.services.source_contour import resolve_source_contour
    _source_contour = resolve_source_contour(card.get("source_table"))
    _law_label = _source_contour.get("law_label", "")

    # ── Render ─────────────────────────────────────────────────────────────
    with st.container(border=True):
        # Топ-бар
        st.markdown(
            f'<div class="cc-card-topbar">'
            f'<span class="cc-badge" style="background:{badge_bg};color:{badge_color};">'
            f'{badge_emoji}{badge_label}</span>'
            f'<span class="cc-status-chip">{_law_label} · {status_icon} {status_label}</span>'
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

        # Human state summary line
        human_parts = []
        if _expert_scope == "IN_CATEGORY" and _expert_cats:
            human_parts.append(f"В категории: <b>{', '.join(_expert_cats)}</b>")
        elif _expert_scope == "OUT_OF_CATEGORY":
            human_parts.append("Вне товарных категорий")
        elif _expert_scope == "UNCERTAIN":
            human_parts.append("Не уверен")
        elif _expert is None:
            human_parts.append("Не размечено")
        if _expert_medal_val and _expert_scope == "IN_CATEGORY":
            human_parts.append(f"Медаль: <b>{_expert_medal_val}</b>")
        if is_assessed:
            human_parts.append(f"<span style='color:#94a3b8'>ИИ предложил: {ai_status}</span>")

        st.markdown(
            '<div class="cc-ai-meta">' + " · ".join(human_parts) + "</div>",
            unsafe_allow_html=True,
        )

        # ── ALWAYS-VISIBLE TABS ────────────────────────────────────────────
        t_overview, t_ai, t_medals, t_docs, t_history, t_annotation = st.tabs([
            "📋 ОБЗОР", "🤖 AI / КАТЕГОРИИ", "🏅 МЕДАЛИ", "📁 ДОКУМЕНТЫ", "📜 ИСТОРИЯ", "✍️ РАЗМЕТКА"
        ])

        # TAB: ОБЗОР ──────────────────────────────────────────────────────
        with t_overview:
            # Human annotation summary
            st.markdown('<div class="cc-section">Статус разметки</div>', unsafe_allow_html=True)
            if _expert_scope == "IN_CATEGORY":
                cats_display = ", ".join(_expert_cats) if _expert_cats else "—"
                st.markdown(f"✅ **В категории:** `{cats_display}`")
                if _expert_medal_val:
                    st.markdown(f"**Медаль:** {_MEDAL_EMOJI.get(_expert_medal_val, '')}`{_expert_medal_val}`")
                comm_entry = _expert_payload.get("expert_commercial_entry")
                if comm_entry:
                    st.caption(f"Коммерческая оценка: `{comm_entry}`")
            elif _expert_scope == "OUT_OF_CATEGORY":
                st.markdown("⛔ **Вне товарных категорий**")
                reason = _expert_payload.get("expert_rejection_reason") or _expert_payload.get("out_of_category_reason")
                if reason:
                    st.caption(f"Причина: `{reason}`")
            elif _expert_scope == "UNCERTAIN":
                st.markdown("❓ **Не уверен** — требует уточнения")
            elif _expert is not None:
                st.markdown("📝 Размечено (legacy)")
            else:
                st.info("🔘 Закупка ещё не размечена экспертом.")

            if is_assessed:
                st.markdown('<div class="cc-section">ИИ предложил (только чтение)</div>', unsafe_allow_html=True)
                _eff_obj = (effective.object_type if effective else None) or "—"
                _eff_proc = (effective.procurement_type if effective else None) or "—"
                st.caption(f"Object: `{_eff_obj}` · Procurement: `{_eff_proc}` · AI status: `{ai_status}`")

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
            eff_route = (effective.route_profile if effective else None) or "—"
            eff_obj   = (effective.object_type   if effective else None) or "—"
            eff_proc  = (effective.procurement_type if effective else None) or "—"
            eff_reasons = (effective.reasons if effective else "—") or "—"
            eff_opps  = (effective.category_opportunities if effective else [])
            render_ai_tab(
                crm_db, crm_id,
                eff_route, eff_obj, eff_proc,
                eff_reasons, eff_opps,
                ai_status=ai_status,
            )

        # TAB: МЕДАЛИ ─────────────────────────────────────────────────────
        with t_medals:
            eff_medal = (effective.best_candidate_level if effective else None)
            eff_score = (effective.best_candidate_score if effective else None)
            eff_reasons_m = (effective.reasons if effective else "—") or "—"
            eff_opps_m = (effective.category_opportunities if effective else [])
            render_medals_tab(
                crm_db, crm_id, eff_opps_m,
                ai_cand_medal=eff_medal,
                ai_cand_score=eff_score,
                ai_reasons=eff_reasons_m,
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

            eff_research = (effective.overall_research_action if effective else None) or "METADATA_ONLY"
            st.markdown(
                f"**Статус:** `{stage}`  \n"
                f"**Research action:** `{eff_research}`"
            )

            eff_opps_d = (effective.category_opportunities if effective else [])
            if eff_opps_d:
                st.markdown("#### Действия по категориям:")
                for opp in eff_opps_d:
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

        # TAB: РАЗМЕТКА ───────────────────────────────────────────────────
        with t_annotation:
            from src.services.expert_annotation_service import load_model_assessment_for_annotation
            from src.ui.components.analytics_v2.annotation_card import render_annotation_section

            assessment_data = load_model_assessment_for_annotation(crm_id, crm_db)

            render_annotation_section(
                crm_db=crm_db,
                procurement_id=crm_id,
                header=card,
                assessment=assessment_data,
                existing_annotation=_expert,
                section="Первое решение"
            )
