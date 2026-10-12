"""Nested UK activity sections: objects, touches, surveys, quotes, documents, AI."""
from __future__ import annotations

from typing import Any

import streamlit as st

from src.services.map_export import rows_to_geojson
from src.services.waterproofing_contour import (
    ask_contour_ai,
    contour_ai_payload,
    fallback_next_step_script,
    load_contour_history,
    merge_contour_state,
)
from src.ui.map_view import render_map

_RECORD_SECTIONS: dict[str, dict[str, Any]] = {
    "surveys": {
        "title": "🔍 Обследования",
        "fields": (("Дата", "date"), ("Объект", "object"), ("Дефекты", "defects"),
                   ("Вывод / технология", "conclusion")),
    },
    "quotes": {
        "title": "📄 КП / техрешение",
        "fields": (("Дата", "date"), ("Объект", "object"), ("Сумма", "amount"),
                   ("Статус", "status")),
    },
    "documents": {
        "title": "📁 Документы",
        "fields": (("Дата", "date"), ("Документ", "name"), ("Тип", "kind"),
                   ("Ссылка / номер", "link")),
    },
}


def _render_records(key: str, state: dict[str, Any], section: str) -> None:
    spec = _RECORD_SECTIONS[section]
    records = list(state.get(section) or [])
    if records:
        st.dataframe(
            [{label: record.get(field, "") for label, field in spec["fields"]} for record in records],
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("Записей пока нет.")
    with st.form(key=f"hydro_add_{section}_{key}", clear_on_submit=True):
        values: dict[str, str] = {}
        for column, (label, field) in zip(st.columns(len(spec["fields"])), spec["fields"]):
            values[field] = column.text_input(label)
        if st.form_submit_button("Добавить запись"):
            if any(str(value).strip() for value in values.values()):
                merge_contour_state(key, {
                    section: records + [{k: str(v).strip() for k, v in values.items()}]
                })
                st.success("Запись добавлена в карточку УК.")
                st.rerun()
            st.warning("Заполните хотя бы одно поле.")


def _render_history(key: str) -> None:
    history = list(reversed(load_contour_history(key)))
    if not history:
        st.caption("Касаний пока не зафиксировано.")
        return
    st.caption("Каждое сохранение карточки добавляет запись в историю.")
    st.dataframe([{
        "Дата": row.get("updated_at"), "Этап": row.get("stage"),
        "Следующее действие": row.get("next_action"),
        "Дата касания": row.get("next_action_date"),
        "Ответственный": row.get("responsible"), "Комментарий": row.get("note"),
    } for row in history], use_container_width=True, hide_index=True)


def _render_priority_cards(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    st.markdown("### Приоритетные объекты портфеля")
    for row in sorted(rows, key=lambda item: int(item.get("hydro_score") or 0), reverse=True)[:10]:
        with st.container(border=True):
            st.markdown(f"**{row.get('hydro_icon') or '🅿️'} {row.get('name') or row.get('address') or 'Объект'}**")
            st.caption(row.get("address") or "")
            for column, label, value in zip(st.columns(5), ("Приоритет", "Подземка", "Площадь", "Уверенность", "КН"), (
                f"{row.get('hydro_grade') or '—'} / {int(row.get('hydro_score') or 0)}",
                row.get("floors_underground") or "—", row.get("area_total") or "—",
                f"{float(row.get('confidence_score') or 0):.2f}", row.get("cadastral_number") or "—",
            )):
                column.metric(label, value)


def _render_objects(rows: list[dict[str, Any]], ogrn: str | None) -> None:
    if not rows:
        st.info("По этой УК нет объектов с координатами. Проверьте привязку УК в базе.")
        return
    st.caption(f"Объектов в портфеле УК: **{len(rows)}**")
    if st.toggle("Показать карту объектов УК", key=f"hydro_uk_map_{ogrn}"):
        render_map(rows_to_geojson(rows), zoom=12, highlight_ogrn=ogrn)
    st.dataframe([{
        "Объект": row.get("name") or row.get("address"), "Адрес": row.get("address"),
        "Подземных этажей": row.get("floors_underground"), "Площадь": row.get("area_total"),
        "Приоритет": row.get("hydro_grade"), "Hydro score": row.get("hydro_score"),
        "КН": row.get("cadastral_number"),
    } for row in rows[:200]], use_container_width=True, hide_index=True)
    _render_priority_cards(rows)


def _render_ai(key: str, card: dict[str, Any], state: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    st.caption("AI использует данные УК и приоритетных объектов. Проверяйте ответ перед фиксацией в CRM.")
    st.code(fallback_next_step_script(card, state, rows), language="text")
    if st.button("Сформировать следующий шаг с AI", key=f"hydro_ai_{key}", type="primary"):
        with st.spinner("AI формирует следующий шаг по УК…"):
            st.session_state[f"hydro_ai_answer_{key}"] = ask_contour_ai(card, state, rows)
    answer = st.session_state.get(f"hydro_ai_answer_{key}")
    if answer:
        st.markdown("#### Ответ AI")
        st.write(answer)
    with st.expander("Контекст, который уходит в AI"):
        st.json(contour_ai_payload(card, state, rows))
    st.markdown("#### Регламент ведения контура")
    st.markdown(
        "1. Держать по каждому контуру тех. контакт и дату следующего касания.\n"
        "2. Не переводить УК дальше без зафиксированного результата шага.\n"
        "3. Объекты выбирать после встречи с эксплуатацией.\n"
        "4. После обследования сразу фиксировать дефекты и КП в карточке."
    )


def render_uk_activity(
    key: str, card: dict[str, Any], state: dict[str, Any], object_rows: list[dict[str, Any]],
    ogrn: str | None,
) -> None:
    """Render everything nested inside the UK card after the summary and next step."""
    st.markdown("### Вложенные данные по УК")
    tabs = st.tabs([
        "🏗️ Объекты УК", "📞 История касаний", "🔍 Обследования", "📄 КП",
        "📁 Документы", "🤖 AI-рекомендации",
    ])
    with tabs[0]:
        _render_objects(object_rows, ogrn)
    with tabs[1]:
        _render_history(key)
    with tabs[2]:
        _render_records(key, state, "surveys")
    with tabs[3]:
        _render_records(key, state, "quotes")
    with tabs[4]:
        _render_records(key, state, "documents")
    with tabs[5]:
        _render_ai(key, card, state, object_rows)
