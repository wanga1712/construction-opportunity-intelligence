"""Детальная карточка объекта для нового аналитического контура."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.services.docs_match_preview import confirmed_product_groups, products_for_group


def render_object_detail(item, groups_map: dict[str, str]) -> None:
    """Ленивая детальная карточка нового формата."""
    top_left, top_right = st.columns([4, 2])
    with top_left:
        if st.button("← Назад", key="detail_back"):
            st.session_state.pop("selected_object_id", None)
            st.query_params.pop("object_id", None)
            st.rerun()
        st.title(item.name)
        st.caption(
            f"{item.region or '—'} · Обновлено: {item.end_date or item.delivery_end_date or 'дата не указана'}"
        )
    with top_right:
        actions = st.columns(3)
        actions[0].button("В портфель", use_container_width=True, key="detail_portfolio")
        actions[1].button("Следить", use_container_width=True, key="detail_watch")
        actions[2].button("Экспорт", use_container_width=True, key="detail_export")

    cols = st.columns(4)
    cols[0].metric("Стадия", item.pipeline_stage_label or "—", border=True)
    cols[1].metric("Рейтинг", int(item.ai_priority_score or 0), border=True)
    cols[2].metric(
        "Уверенность AI", f"{int(item.ai_classification_confidence or 0)}%", border=True
    )
    cols[3].metric("Категории", len(confirmed_product_groups(item)), border=True)

    tabs = st.tabs(
        ["Обзор", "Материалы", "Документы", "Участники", "История", "AI и обучение", "Похожие"]
    )
    with tabs[0]:
        with st.container(border=True):
            st.markdown("**Объект**")
            st.write(f"Точное название: {item.name}")
            st.write(f"Регион: {item.region or '—'}")
            st.write(f"Адрес: {item.address or '—'}")
            st.write(f"Текущая стадия: {item.pipeline_stage_label or '—'}")
            st.write(f"Следующий шаг: {item.ai_manager_next_step or '—'}")
        with st.container(border=True):
            st.markdown("**Почему карточка такого уровня**")
            st.write(
                item.ai_card_status_reason
                or item.ai_priority_reason
                or "Объяснение пока не подготовлено."
            )
    with tabs[1]:
        with st.container(border=True):
            st.markdown("**Товарные возможности**")
            for code in sorted(confirmed_product_groups(item)):
                label = groups_map.get(code, code)
                st.write(
                    f"{label}: {', '.join(products_for_group(item, code)[:5]) or 'без расшифровки'}"
                )
    with tabs[2]:
        df = pd.DataFrame(
            [
                {
                    "Документ": "Совпадения в документах",
                    "Тип": "Матчинг",
                    "Обработан": "Да" if (item.doc_matches or 0) > 0 else "Нет",
                    "Совпадений": int(item.doc_matches or 0),
                    "Ошибка": "Нет",
                    "Действие": "Открыть",
                }
            ]
        )
        st.dataframe(df, hide_index=True, use_container_width=True)
    with tabs[3]:
        st.write(f"Заказчик: {item.balance_holder or item.customer_name or '—'}")
        st.write(f"Проектировщик: {item.expertise_planner or '—'}")
        st.write(f"Подрядчик: {item.contractor_name or 'Пока не определён'}")
    with tabs[4]:
        st.write("История объекта")
        st.write(f"Объект найден: {item.start_date or '—'}")
        st.write(f"Текущая стадия: {item.pipeline_stage_label or '—'}")
        st.write(f"Документы обработаны: {int(item.doc_matches or 0)} совпадений")
    with tabs[5]:
        with st.status("AI-классификация", expanded=True) as status:
            status.write(
                f"Модель: локальная классификация · Уверенность: {int(item.ai_classification_confidence or 0)}%"
            )
            status.write(
                f"Ответ AI: {item.ai_priority_reason or item.ai_card_status_reason or '—'}"
            )
            status.update(label="Проверка доступна", state="complete")
    with tabs[6]:
        st.info("Похожие объекты будут подтянуты отдельным сервисом.")
