"""Early object radar: expertise conclusions and future RSS/news signals."""
from __future__ import annotations

import json

import streamlit as st

from src.services.opportunity_radar import (
    AVERAGE_DAYS_TO_TENDER,
    RadarFilters,
    build_radar_ai_payload,
    fetch_expertise_radar,
    product_filter_options,
    rss_placeholder_rows,
)
from src.services.unified_radar_service import UnifiedRadarService


PHASE_LABELS = {
    "hot_expected": "скоро ожидаем торги",
    "warm_expected": "тёплый объект",
    "nurture": "греть / наблюдать",
    "early_watch": "ранний сигнал",
    "overdue_check_tender": "проверить, не вышел ли уже",
    "tender_docs_pending": "торги есть, ждём разбор документов",
    "no_date": "нет даты",
    "planned": "будущий RSS-сигнал",
}


def render_opportunity_radar_page(service) -> None:
    st.title("Радар объектов")
    st.caption(
        "Ранние сигналы до подтверждённых материалов в документах: положительные заключения, "
        "ПИР/проекты, закупки без разобранных документов. "
        f"Средний прогноз выхода на торги: +{AVERAGE_DAYS_TO_TENDER} дней от даты заключения. "
        "Закупочный контур — только после `doc_matches > 0`."
    )

    f1, f2, f3, f4, f5 = st.columns([1.4, 1.1, 1, 1, 1])
    with f1:
        region_query = st.text_input("Регион / адрес", placeholder="Москва, Кировск, Ставрополь…")
    with f2:
        product_label_map = {label: code for code, label in product_filter_options()}
        product_label = st.selectbox(
            "Товарный интерес",
            list(product_label_map.keys()),
            key="radar_product_group",
        )
        product_group = product_label_map[product_label]
    with f3:
        only_without_tender = st.toggle("Только без найденной закупки", value=False)
    with f4:
        horizon_days = st.selectbox("Глубина экспертиз", [180, 365, 730, 1095], index=1)
    with f5:
        limit = st.selectbox("Лимит", [50, 100, 200, 500], index=2)

    u_service = UnifiedRadarService(tender_db=service.tender_db, radar_db=service.radar_db)
    u_result = u_service.load(
        RadarFilters(
            region_query=region_query,
            only_without_tender=only_without_tender,
            product_group=product_group,
            horizon_days=int(horizon_days),
            limit=int(limit),
        )
    )

    tabs = st.tabs(["NashDom", "Положительные заключения", "План закупок", "Unified", "AI-контекст"])

    with tabs[0]:
        rows = u_result.nashdom_rows
        st.caption("Сигналы объектов из NashDom (ранний канал).")
        st.metric("NashDom объектов", len(rows))
        if not rows:
            st.info("Нет данных NashDom по выбранным фильтрам.")
        for row in rows[: int(limit)]:
            with st.container(border=True):
                st.markdown(f"**{row.get('object_name') or 'Объект'}**")
                st.caption(" · ".join(filter(None, [str(row.get("region_name") or ""), str(row.get("full_address") or "")])))
                st.caption(f"NashDom ID: {row.get('object_id') or '—'}")

    with tabs[1]:
        rows = u_result.positive_rows
        if not rows:
            st.warning("Нет объектов по выбранным фильтрам.")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Всего сигналов", len(rows))
            m2.metric("Ждём документы", sum(1 for r in rows if r.get("radar_phase") == "tender_docs_pending"))
            m3.metric("Скоро торги", sum(1 for r in rows if r.get("radar_phase") in ("hot_expected", "overdue_check_tender")))
            m4.metric("Без закупки", sum(1 for r in rows if not r.get("tender_match_count")))
            for row in sorted(rows, key=lambda r: int(r.get("radar_priority") or 0), reverse=True):
                _render_radar_card(row)

    with tabs[2]:
        rows = u_result.procurement_plan_rows
        st.caption("План закупок из таблиц ЕИС на 7-м (если таблица доступна).")
        st.metric("Плановых позиций", len(rows))
        if not rows:
            st.info("Таблица плана закупок не найдена или данных нет.")
        for row in rows[: int(limit)]:
            with st.container(border=True):
                st.markdown(f"**{row.get('object_name') or 'Позиция плана'}**")
                st.caption(" · ".join(filter(None, [str(row.get("region_name") or ""), str(row.get("customer_name") or "")])))
                st.caption(f"План публикации: {str(row.get('planned_publish_date') or '—')[:10]}")

    with tabs[3]:
        st.caption("Объединённые карточки из 3 каналов: NashDom + положительные + план закупок.")
        cards = u_result.unified_cards
        c1, c2, c3 = st.columns(3)
        c1.metric("Unified карточек", len(cards))
        c2.metric("Golden lead", sum(1 for x in cards if x.status == "golden_lead"))
        c3.metric("С прогнозом торгов", sum(1 for x in cards if x.predicted_tender_date))
        if not cards:
            st.info("Нет unified карточек по текущим фильтрам.")
        for card in cards:
            _render_unified_card(card)

    with tabs[4]:
        st.markdown("### Что передаём в AI")
        st.caption(
            "AI должен видеть источник, участников, регион, прогноз торгов и ранний товарный интерес. "
            "Материалы утверждать нельзя, пока нет совпадений в документации."
        )
        sample = u_result.positive_rows[0] if u_result.positive_rows else rss_placeholder_rows()[0]
        st.code(json.dumps(build_radar_ai_payload(sample), ensure_ascii=False, indent=2), language="json")


def _render_radar_card(row: dict) -> None:
    phase = row.get("radar_phase") or "no_date"
    label = PHASE_LABELS.get(phase, phase)
    priority = int(row.get("radar_priority") or 0)
    days = row.get("days_to_predicted_tender")
    predicted = row.get("predicted_tender_date") or "—"
    interests = row.get("product_interest_labels") or []

    with st.container(border=True):
        head_left, head_right = st.columns([4, 1])
        with head_left:
            st.markdown(f"**{row.get('object_name') or 'Объект без названия'}**")
            st.caption(row.get("region_name") or "регион не указан")
        with head_right:
            st.metric("Приоритет", priority)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Статус", label)
        c2.metric("Прогноз торгов", predicted)
        c3.metric("Дней до прогноза", days if days is not None else "—")
        c4.metric("Найд. закупок", int(row.get("tender_match_count") or 0))

        if interests:
            chips = " · ".join(f"≈ {name}" for name in interests)
            st.caption(f"Ранний товарный сигнал (эвристика): {chips}")

        chips = []
        if row.get("expertise_number"):
            chips.append(f"Эксп. {row.get('expertise_number')}")
        if row.get("developer_organization_info"):
            chips.append(f"Застройщик: {row.get('developer_organization_info')}")
        if row.get("technical_customer_organization_info"):
            chips.append(f"Техзаказчик: {row.get('technical_customer_organization_info')}")
        if row.get("planner_organization_info"):
            chips.append(f"Проектировщик: {row.get('planner_organization_info')}")
        if chips:
            st.caption(" · ".join(str(x) for x in chips[:4]))

        with st.expander("AI payload / будущая карточка"):
            st.code(json.dumps(build_radar_ai_payload(row), ensure_ascii=False, indent=2), language="json")


def _render_unified_card(card) -> None:
    """Показывает сводную карточку и статус сигналов по контурам."""
    flags = card.signal_flags
    found = lambda x: "найдено" if x else "не найдено"
    with st.container(border=True):
        h1, h2 = st.columns([4, 1])
        with h1:
            st.markdown(f"**{card.object_name or 'Объект'}**")
            st.caption(" · ".join(filter(None, [card.region_name, card.address])))
        with h2:
            st.metric("AI приоритет", int(card.ai_priority_score or 0))
        st.caption(
            f"Статус: {card.status} · источники: {', '.join(card.sources) if card.sources else '—'}"
        )
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Положит. заключение", found(flags.positive_expertise))
        b2.metric("Проектировщик", found(flags.projector_found))
        b3.metric("Заказчик", found(flags.customer_found))
        b4.metric("Закупка найдена", found(flags.tender_found))
        p_date = card.predicted_tender_date.isoformat() if card.predicted_tender_date else "—"
        st.caption(
            f"Прогноз торгов (+240 дней): {p_date} · "
            f"дней до прогноза: {card.days_to_predicted_tender if card.days_to_predicted_tender is not None else '—'}"
        )
