"""Superuser UI page for OKPD Research Taxonomy management and live score preview."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import streamlit as st

from src.learning.okpd_prior.combined_v2 import ResearchPriorityModelV2
from src.learning.okpd_prior.disambiguation import extract_domain_signals
from src.learning.okpd_prior.model import assign_priority_band
from src.learning.okpd_prior.semantic_model import TitleSemanticModelV2
from src.models.taxonomy_rules import (
    MODE_BOOST,
    MODE_DOWNWEIGHT,
    MODE_EXCLUDE_FROM_PRIMARY,
    MODE_EXPLORE,
    MODE_NEUTRAL,
    PROPOSAL_STATUS_PENDING,
    VALID_RULE_MODES,
)
from src.repositories.taxonomy_repository import TaxonomyRepository
from src.services.taxonomy_service import TaxonomyService


def render_taxonomy_management_page(
    taxonomy_service: Optional[TaxonomyService] = None,
    combined_model: Optional[ResearchPriorityModelV2] = None,
) -> None:
    """Renders the Streamlit Superuser Research Taxonomy management interface."""
    st.title("🏛️ Управление исследовательской таксономией ОКПД (Superuser)")
    st.caption("Настройка приоритетов ОКПД, разбор предложений и симулятор скоринга V2")

    if taxonomy_service is None:
        taxonomy_service = TaxonomyService()

    tab_rules, tab_proposals, tab_simulator, tab_audit = st.tabs([
        "📋 Активные правила",
        "💡 Предложения от ИИ / Доказательств",
        "🔬 Симулятор скоринга V2",
        "📜 Журнал аудита",
    ])

    # 1. TAB: Active Rules
    with tab_rules:
        st.subheader("Правила таксономии ОКПД")
        rules = taxonomy_service.repository.get_all_rules(active_only=True)
        if rules:
            rule_data = [
                {
                    "ID": r.rule_id,
                    "Паттерн ОКПД": r.okpd_pattern,
                    "Режим": r.rule_mode,
                    "Корректировка": f"{r.adjustment_weight:+.2f}",
                    "Обоснование": r.reason,
                    "Создал": r.created_by,
                    "Дата": r.created_at[:19] if r.created_at else "",
                }
                for r in rules
            ]
            st.dataframe(rule_data, use_container_width=True)
        else:
            st.info("Активные правила таксономии пока не созданы.")

        st.divider()
        st.markdown("#### Добавить / изменить правило")
        with st.form("add_rule_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                new_okpd = st.text_input("Префикс / Код ОКПД", placeholder="например, 42.11.20 или 26")
            with col2:
                new_mode = st.selectbox("Режим правила", list(VALID_RULE_MODES))
            with col3:
                new_weight = st.number_input("Вес корректировки", min_value=-1.0, max_value=1.0, value=0.25, step=0.05)

            new_reason = st.text_input("Обоснование правила", placeholder="Причина повышения / понижения приоритета")
            submit = st.form_submit_button("💾 Сохранить правило")

            if submit and new_okpd:
                taxonomy_service.create_or_update_rule(
                    okpd_pattern=new_okpd,
                    rule_mode=new_mode,
                    adjustment_weight=new_weight,
                    reason=new_reason,
                    actor="superuser",
                )
                st.success(f"Правило для '{new_okpd}' сохранено!")
                st.rerun()

    # 2. TAB: Proposals
    with tab_proposals:
        st.subheader("Предложения на основе фактических исследований")
        proposals = taxonomy_service.repository.get_all_proposals(status=PROPOSAL_STATUS_PENDING)
        if proposals:
            for p in proposals:
                with st.expander(f"Предложение {p.proposal_id}: ОКПД {p.okpd_pattern} ({p.proposed_mode})"):
                    st.write(f"**Обоснование:** {p.evidence_summary}")
                    st.write(f"**Статистика:** Подтверждено: {p.positive_count}, Отклонено: {p.negative_count}")
                    st.write(f"**Примеры ID закупок:** {p.sample_pids}")
                    col_app, col_rej = st.columns([1, 1])
                    if col_app.button("✅ Одобрить", key=f"app_{p.proposal_id}"):
                        taxonomy_service.approve_proposal(p.proposal_id, actor="superuser")
                        st.success(f"Предложение {p.proposal_id} одобрено!")
                        st.rerun()
                    if col_rej.button("❌ Отклонить", key=f"rej_{p.proposal_id}"):
                        taxonomy_service.reject_proposal(p.proposal_id, actor="superuser")
                        st.warning(f"Предложение {p.proposal_id} отклонено.")
                        st.rerun()
        else:
            st.info("Нет новых предложений, ожидающих рассмотрения.")

    # 3. TAB: Score Preview Simulator
    with tab_simulator:
        st.subheader("🔬 Симулятор декомпозиции скоринга V2")
        st.caption("Введите параметры закупки для проверки работы модели V2 и таксономии")

        sim_title = st.text_area(
            "Название закупки (auction_name)",
            value="Выполнение работ по капитальному ремонту и гидроизоляции деформационных швов мостового перехода",
        )
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            sim_okpd = st.text_input("Код ОКПД", value="42.11.20.200")
        with col_s2:
            sim_price = st.number_input("Начальная цена, руб.", value=15000000.0, step=100000.0)

        if st.button("🚀 Рассчитать скоринг"):
            # Domain signals
            sig = extract_domain_signals(sim_title, sim_okpd)
            
            # Predict probability if model available
            if combined_model and combined_model.is_fitted:
                model_score = combined_model.predict_one(sim_title, sim_okpd, sim_price)
            else:
                # Heuristic fallback for preview if model not passed
                base = 0.50 if sig["construction_prior"] > 0 else 0.10
                if sig["disambiguated_injection_score"] > 0:
                    base = 0.85
                elif sig["medical_risk"] > 0.5:
                    base = 0.05
                model_score = base

            tax_res = taxonomy_service.compute_adjusted_priority(model_score, sim_okpd)
            final_p = tax_res["final_shadow_score"]
            band = assign_priority_band(final_p)

            st.divider()
            st.markdown("### Результаты декомпозиции:")
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("P(Model V2)", f"{model_score:.4f}")
            m2.metric("Корректировка таксономии", f"{tax_res['taxonomy_adjustment']:+.2f}")
            m3.metric("Итоговый Shadow Score", f"{final_p:.4f}")
            m4.metric("Медаль приоритета", band)

            st.write(f"**Совпавшее правило таксономии:** `{tax_res['matched_pattern']}` ({tax_res['rule_mode']}) — {tax_res['reason']}")
            
            with st.expander("🔍 Детальные сигналы доменов:"):
                st.json(sig)

    # 4. TAB: Audit Log
    with tab_audit:
        st.subheader("Журнал действий суперпользователя")
        logs = taxonomy_service.repository.get_audit_logs(limit=50)
        if logs:
            log_data = [
                {
                    "Дата": l.timestamp[:19] if l.timestamp else "",
                    "Действие": l.action,
                    "Пользователь": l.actor,
                    "Детали": l.details,
                }
                for l in logs
            ]
            st.dataframe(log_data, use_container_width=True)
        else:
            st.info("Журнал аудита пуст.")
