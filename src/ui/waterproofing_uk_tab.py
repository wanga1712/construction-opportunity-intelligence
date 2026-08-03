"""Management-company contour tab for waterproofing CRM."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st

from src.services.map_export import MapFilters, fetch_map_objects, fetch_uk_summary, rows_to_geojson
from src.services.objects_service import ObjectsService
from src.services.waterproofing_contour import (
    CONTOUR_STAGES, FIRST_STEP_OPTIONS, ask_contour_ai, contour_ai_payload, contour_key,
    fallback_next_step_script, load_contour_states, save_contour_state,
)
from src.ui.map_view import render_map
from src.ui.session_deps import get_parking_db


def _next_date(state: dict[str, Any]) -> date:
    try:
        return date.fromisoformat(state["next_action_date"])
    except (KeyError, TypeError, ValueError):
        return date.today() + timedelta(days=1)


def _render_saved_contours(states: list[dict[str, Any]]) -> None:
    if not states:
        return
    with st.expander("📋 Контуры в работе", expanded=True):
        rows = [{
            "УК": state.get("uk_name"), "Этап": state.get("stage"),
            "Следующее действие": state.get("next_action"), "Дата": state.get("next_action_date"),
            "Контакт эксплуатации": state.get("exploitation_contact"),
            "Телефон": state.get("secretary_phone") or state.get("uk_phone"),
            "Объектов": state.get("object_count"),
        } for state in sorted(states, key=lambda state: (
            state.get("next_action_date") or "9999-12-31", state.get("uk_name") or ""
        ))]
        st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_company_card(selected: dict[str, Any], state: dict[str, Any]) -> None:
    st.markdown("### Карточка управляющей компании")
    with st.container(border=True):
        columns = st.columns(4)
        for column, label, value in zip(columns, ("Объектов", "≥2 подземных этажа", "ИНН", "ОГРН"), (
            int(selected.get("object_count") or 0), int(selected.get("ge2_floors") or 0),
            selected.get("uk_inn") or "—", selected.get("uk_ogrn") or "—",
        )):
            column.metric(label, value)
        st.markdown(f"**{selected.get('uk_name') or '—'}**")
        st.caption(f"Телефон: {selected.get('uk_phone') or '—'}")
        if state:
            st.success(
                f"CRM-этап: {state.get('stage') or '—'} · следующее действие: "
                f"{state.get('next_action') or '—'} · дата: {state.get('next_action_date') or '—'}"
            )
        else:
            st.warning("Контур ещё не квалифицирован: начните с секретаря / общего телефона.")
        st.info("Сначала работаем с этим контуром/УК, затем выбираем объекты для обследования, ТКП и торгов.")


def _render_qualification(selected: dict[str, Any], state: dict[str, Any], key: str) -> None:
    st.markdown("### Первый шаг квалификации контура")
    with st.container(border=True):
        st.caption("Цель — выйти через секретаря на эксплуатацию и договориться о встрече по портфелю подземных помещений.")
        left, right = st.columns([1.2, 1])
        with left:
            stage_default = state.get("stage") or CONTOUR_STAGES[0]
            stage = st.selectbox("Этап контура", CONTOUR_STAGES,
                index=CONTOUR_STAGES.index(stage_default) if stage_default in CONTOUR_STAGES else 0,
                key=f"hydro_stage_{key}")
            action_default = state.get("next_action") or FIRST_STEP_OPTIONS[0]
            next_action = st.selectbox("Следующее действие", FIRST_STEP_OPTIONS,
                index=FIRST_STEP_OPTIONS.index(action_default) if action_default in FIRST_STEP_OPTIONS else 0,
                key=f"hydro_next_{key}")
            note = st.text_area("Комментарий / результат звонка", value=state.get("note") or "",
                placeholder="Например: секретарь сказала звонить завтра после 11:00.",
                key=f"hydro_note_{key}")
        with right:
            secretary_phone = st.text_input("Телефон секретаря / общий",
                value=state.get("secretary_phone") or selected.get("uk_phone") or "",
                key=f"hydro_secretary_phone_{key}")
            exploitation_contact = st.text_input("Начальник эксплуатации / тех. контакт",
                value=state.get("exploitation_contact") or "", placeholder="ФИО, должность, телефон",
                key=f"hydro_exploitation_contact_{key}")
            next_action_date = st.date_input("Дата следующего касания", value=_next_date(state),
                key=f"hydro_next_date_{key}")
            responsible = st.text_input("Ответственный", value=state.get("responsible") or "<S13_SSH_USER>",
                key=f"hydro_responsible_{key}")
        if st.button("Сохранить первый шаг по УК", key=f"hydro_save_contour_{key}", type="primary"):
            save_contour_state(key, {
                "uk_name": selected.get("uk_name"), "uk_ogrn": selected.get("uk_ogrn"),
                "uk_inn": selected.get("uk_inn"), "uk_phone": selected.get("uk_phone"),
                "object_count": int(selected.get("object_count") or 0),
                "ge2_floors": int(selected.get("ge2_floors") or 0), "stage": stage,
                "next_action": next_action, "next_action_date": next_action_date.isoformat(),
                "secretary_phone": secretary_phone, "exploitation_contact": exploitation_contact,
                "responsible": responsible, "note": note,
            })
            st.success("Контур УК сохранён. Теперь его можно вести как CRM-карточку заказчика.")
            st.rerun()


def _render_ai_next_step(selected: dict[str, Any], state: dict[str, Any], rows: list[dict[str, Any]], key: str) -> None:
    if not state:
        return
    st.markdown("### AI: следующий шаг по контуру")
    with st.container(border=True):
        st.caption("AI использует данные УК и приоритетных объектов; проверяйте ответ перед фиксацией в CRM.")
        st.markdown(f"**Контакт эксплуатации:** {state.get('exploitation_contact') or 'не указан'}")
        st.code(fallback_next_step_script(selected, state, rows), language="text")
        if st.button("Сформировать следующий шаг с AI", key=f"hydro_ai_next_step_{key}"):
            with st.spinner("AI формирует следующий шаг по УК…"):
                st.session_state[f"hydro_ai_next_step_answer_{key}"] = ask_contour_ai(selected, state, rows)
        answer = st.session_state.get(f"hydro_ai_next_step_answer_{key}")
        if answer:
            st.markdown("#### Ответ AI")
            st.write(answer)
        with st.expander("Контекст для AI"):
            st.json(contour_ai_payload(selected, state, rows))


def _render_object_tabs(rows: list[dict[str, Any]], selected_ogrn: str | None) -> None:
    tab_map, tab_objects, tab_recommendations = st.tabs(["🗺 Карта объектов УК", "🏗️ Объекты УК", "🤖 Рекомендации по контуру"])
    with tab_map:
        if rows:
            st.caption(f"На карте объекты выбранной УК: **{len(rows)}**")
            render_map(rows_to_geojson(rows), zoom=12, highlight_ogrn=selected_ogrn)
        else:
            st.warning("По выбранной УК нет объектов с координатами.")
    with tab_objects:
        if not rows:
            st.info("Нет объектов для отображения.")
        for row in rows[:100]:
            with st.container(border=True):
                st.markdown(f"**{row.get('name') or row.get('address') or 'Объект'}**")
                st.caption(row.get("address") or "")
                for column, label, value in zip(st.columns(4), ("Подземных этажей", "Площадь", "Confidence", "КН"), (
                    row.get("floors_underground") or "—", row.get("area_total") or "—",
                    f"{float(row.get('confidence_score') or 0):.2f}", row.get("cadastral_number") or "—",
                )):
                    column.metric(label, value)
        _render_priority_cards(rows)
    with tab_recommendations:
        st.markdown("#### Как вести этот контур")
        st.write("1. Выбрать 3–5 адресов с подземными этажами.\n\n2. Найти технический контакт.\n\n3. Запросить проблемные помещения.\n\n4. Предложить обследование и фотофиксацию.\n\n5. После обследования завести сделку по объекту.")


def _render_priority_cards(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    st.markdown("### Приоритетные карточки паркингов")
    for row in sorted(rows, key=lambda item: int(item.get("hydro_score") or 0), reverse=True)[:20]:
        with st.container(border=True):
            st.markdown(f"**{row.get('hydro_icon') or '🅿️'} {row.get('name') or row.get('address') or 'Объект'}**")
            st.caption(row.get("address") or "")
            for column, label, value in zip(st.columns(5), ("Приоритет", "Подземка", "Площадь", "Уверенность", "КН"), (
                f"{row.get('hydro_grade') or '—'} / {int(row.get('hydro_score') or 0)}",
                row.get("floors_underground") or "—", row.get("area_total") or "—",
                f"{float(row.get('confidence_score') or 0):.2f}", row.get("cadastral_number") or "—",
            )):
                column.metric(label, value)
            st.caption(f"{row.get('hydro_label') or 'Паркинг / подземка'} · {row.get('hydro_reasons') or row.get('candidate_reason') or 'нет причины'}")


def render_uk_tab(service: ObjectsService) -> None:
    """Render the UK-contour workflow with its persistence and map views."""
    st.caption("Для гидроизоляции работа начинается с управляющей компании: один контур может дать несколько объектов.")
    parking_db = get_parking_db()
    if not parking_db.connect():
        st.error(f"НСПД / база паркингов недоступна: {parking_db.last_error}")
        return
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        min_floors = st.selectbox("Подземные этажи", [1, 2, 3, 0], index=0,
            format_func=lambda value: "Любые" if value == 0 else f"≥ {value}", key="hydro_uk_min_floors")
    with c2:
        limit = st.selectbox("Показать УК", [10, 25, 50, 100], index=1, key="hydro_uk_limit")
    with c3:
        query = st.text_input("Поиск УК / ОГРН / ИНН", key="hydro_uk_query").strip().lower()
    rows = fetch_uk_summary(parking_db, min_floors=min_floors)
    if query:
        rows = [row for row in rows if query in " ".join(str(row.get(field) or "").lower() for field in ("uk_name", "uk_ogrn", "uk_inn"))]
    rows = rows[:int(limit)]
    if not rows:
        st.warning("УК по выбранным фильтрам не найдены.")
        return
    states = load_contour_states()
    _render_saved_contours(list(states.values()))
    metrics = st.columns(3)
    for column, label, value in zip(metrics, ("УК / контуров", "Объектов в портфелях", "С ≥2 подземными этажами"), (
        len(rows), sum(int(row.get("object_count") or 0) for row in rows),
        sum(int(row.get("ge2_floors") or 0) for row in rows),
    )):
        column.metric(label, value)
    labels = [f"{row.get('uk_name') or 'Без названия'} · объектов: {row.get('object_count')} · ОГРН {row.get('uk_ogrn') or '—'}" for row in rows]
    selected = rows[labels.index(st.selectbox("Выберите УК / ответственный контур", labels, key="hydro_selected_uk"))]
    key, state, ogrn = contour_key(selected), states.get(contour_key(selected), {}), selected.get("uk_ogrn")
    _render_company_card(selected, state)
    _render_qualification(selected, state, key)
    object_rows = fetch_map_objects(parking_db, MapFilters(min_floors=min_floors, uk_status="DONE", uk_ogrn=ogrn, limit=2000)) if ogrn else []
    _render_ai_next_step(selected, state, object_rows, key)
    _render_object_tabs(object_rows, ogrn)
