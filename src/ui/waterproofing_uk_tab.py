"""Detailed УК card for the waterproofing CRM, opened from the kanban board."""
from __future__ import annotations

from datetime import date
from typing import Any

import streamlit as st

from src.services.map_export import MapFilters, fetch_map_objects, fetch_uk_summary
from src.services.objects_service import ObjectsService
from src.services.waterproofing_615_store import read_uk_summary
from src.services.waterproofing_contour import (
    contour_key,
    latest_contour_state,
    merge_contour_state,
)
from src.services.waterproofing_crm import (
    CRM_CLOSED_STAGE,
    CRM_STAGE_DESCRIPTIONS,
    CRM_STAGE_LABELS,
    CRM_STAGES,
    PRIORITIES,
    STAGE_DEFAULT_ACTIONS,
    build_card,
    next_touch_default,
    normalize_stage,
    parse_date,
)
from src.ui.hydro_uk_panel import render_uk_crm_panel
from src.ui.session_deps import get_parking_db
from src.ui.waterproofing_uk_activity import render_uk_activity


def _planned_date(state: dict[str, Any]) -> date:
    return (
        parse_date(state.get("next_action_date"))
        or parse_date(next_touch_default(state.get("stage")))
        or date.today()
    )


def _render_summary(card: dict[str, Any], tenders_615: dict[str, Any]) -> None:
    st.markdown(f"## {card['uk_name_short']}")
    caption = f"ИНН {card['uk_inn']} · ☎ {card['phone'] or '—'}"
    if card.get("uk_address"):
        caption += f" · 📍 {card['uk_address']}"
    st.caption(caption)
    values = (
        ("Объектов", card["object_count"]),
        ("Паркингов", card["parking_count"]),
        ("Подземных этажей", card["total_underground_floors"]),
        ("Потенциал", card["potential_amount_label"]),
        ("Приоритет", f"{card['priority_icon']} {card['priority']}"),
        ("Этап", card.get("stage_label") or card["stage"]),
    )
    for column, (label, value) in zip(st.columns(len(values)), values):
        column.metric(label, value)
    st.caption(f"Приоритет по объёму работ: {card['priority_reason']}")
    badges = [
        "✅ тех. контакт найден" if card["tech_contact"] else "⛔ тех. контакта нет",
        f"👤 ответственный: {card['responsible']}",
        f"📅 следующее касание: {card['next_action_date'] or 'не назначено'}",
    ]
    if card["overdue"]:
        badges.append(f"🔴 просрочка {card['overdue_days']} дн.")
    st.markdown(" · ".join(badges))
    if tenders_615.get("has_tenders"):
        line = (
            f"🏗 615-ПП: по домам этой УК уже {tenders_615['history_tenders']} торг(ов) "
            f"на {tenders_615['history_amount_label']} (последний — "
            f"{tenders_615.get('history_last_date') or '—'})"
        )
        if tenders_615.get("tenders"):
            line += (
                f", в том числе в {tenders_615.get('year')}: {tenders_615['tenders']} "
                f"на {tenders_615['amount_label']}"
            )
        st.info(line + ".")
    elif tenders_615:
        st.info(
            f"🏗 615-ПП: по {tenders_615.get('checked_addresses') or 0} адресам домов "
            f"этой УК торгов капремонта не найдено "
            f"(история с {tenders_615.get('history_from')} года)."
        )


def _render_615(tenders_615: dict[str, Any]) -> None:
    """Блок 615-ПП: были ли торги по капремонту и на какую сумму."""
    st.markdown("### 615-ПП: капремонт по домам УК")
    if not tenders_615:
        st.caption(
            "Нет данных 615-ПП по этой УК: у неё нет домов с адресами или связка "
            "с реестром капремонта ещё не рассчитана."
        )
        return
    overview = tenders_615.get("overview") or {}
    year = tenders_615.get("year") or overview.get("year") or ""
    left, right, third = st.columns(3)
    left.metric("Торгов по домам УК", tenders_615.get("history_tenders", 0))
    right.metric("Объём по домам УК", tenders_615.get("history_amount_label", "—"))
    third.metric(
        f"Из них в {year}",
        f"{tenders_615.get('tenders', 0)} · {tenders_615.get('amount_label', '—')}",
    )
    if overview:
        st.caption(
            f"Для сравнения, вся программа {overview.get('year')}: "
            f"{overview.get('tenders')} торгов на {overview.get('amount_label')}, "
            f"в том числе гидроизоляция — {overview.get('waterproofing_tenders')} "
            f"на {overview.get('waterproofing_amount_label')}."
        )
    matches = tenders_615.get("matches") or []
    if not matches:
        st.caption(
            f"По {tenders_615.get('checked_addresses') or 0} адресам домов этой УК торгов "
            f"капремонта не найдено (история с {tenders_615.get('history_from')} года). "
            "Сопоставление идёт по «улица + дом»: тип улицы, корпус и округ не различаются."
        )
        return
    st.dataframe(
        [
            {
                "Дом": match["address"],
                "Торгов": match["tenders"],
                "Сумма": match["amount_label"],
                "Годы": ", ".join(str(year) for year in match.get("years") or []),
                "Последний": match["last_date"],
                "Совпадение": match.get("confidence") or "",
            }
            for match in matches
        ],
        use_container_width=True,
        hide_index=True,
    )
    note = "Сопоставление идёт по «улица + дом»: тип улицы, корпус и округ не различаются."
    approximate = tenders_615.get("approximate_matches") or 0
    if approximate:
        note += f" Часть строк ({approximate}) найдена по похожему адресу — проверьте вручную."
    st.caption(note)


def _render_status_form(key: str, card: dict[str, Any], state: dict[str, Any]) -> None:
    st.markdown("### CRM-статус и следующий шаг")
    # A closed contour is not a board column, but its stage must stay selectable
    # and a legacy saved value must never raise here.
    stage_ids = [*CRM_STAGES, CRM_CLOSED_STAGE]
    current_stage = normalize_stage(card["stage"])
    left, right = st.columns(2)
    with left:
        stage = st.selectbox(
            "Этап воронки",
            stage_ids,
            index=stage_ids.index(current_stage) if current_stage in stage_ids else 0,
            format_func=lambda value: CRM_STAGE_LABELS.get(value, value),
            key=f"uk_stage_{key}",
        )
        next_action = st.text_input(
            "Следующее действие",
            value=state.get("next_action") or STAGE_DEFAULT_ACTIONS.get(stage, ""),
            key=f"uk_next_{key}",
        )
        st.caption(CRM_STAGE_DESCRIPTIONS.get(stage, STAGE_DEFAULT_ACTIONS.get(stage, "—")))
        next_date = st.date_input("Дата следующего касания", value=_planned_date(state), key=f"uk_date_{key}")
        responsible = st.text_input("Ответственный", value=state.get("responsible") or "", key=f"uk_resp_{key}")
    with right:
        priority = st.selectbox(
            "Приоритет", PRIORITIES, index=PRIORITIES.index(card["priority"]), key=f"uk_prio_{key}"
        )
        amount = st.text_input(
            "Потенциальная сумма",
            value=str(state.get("potential_amount") or ""),
            placeholder="например 4,2 млн",
            key=f"uk_amount_{key}",
        )
        tech_contact = st.text_input(
            "Тех. контакт (ФИО, должность)",
            value=state.get("exploitation_contact") or "",
            key=f"uk_tech_{key}",
        )
        tech_phone = st.text_input(
            "Телефон тех. контакта", value=state.get("tech_contact_phone") or "", key=f"uk_tech_phone_{key}"
        )
        secretary_phone = st.text_input(
            "Телефон секретаря / общий",
            value=state.get("secretary_phone") or card.get("uk_phone") or "",
            key=f"uk_sec_phone_{key}",
        )
    note = st.text_area(
        "Комментарий / результат касания", value=state.get("note") or "", key=f"uk_note_{key}"
    )
    if st.button("Сохранить и зафиксировать касание", key=f"uk_save_{key}", type="primary"):
        merge_contour_state(key, {
            "uk_name": card["uk_name"], "uk_inn": card["uk_inn"], "uk_ogrn": card["uk_ogrn"],
            "uk_phone": card.get("uk_phone") or state.get("uk_phone") or "",
            "uk_address": card.get("uk_address") or state.get("uk_address") or "",
            "object_count": card["object_count"],
            "parking_count": card["parking_count"],
            "total_underground_floors": card["total_underground_floors"],
            "max_underground_floors": card["max_underground_floors"],
            "ge1_floors": card["ge1_floors"], "ge2_floors": card["ge2_floors"],
            "stage": stage, "next_action": next_action, "next_action_date": next_date.isoformat(),
            "responsible": responsible, "priority": priority, "potential_amount": amount,
            "exploitation_contact": tech_contact, "tech_contact_phone": tech_phone,
            "secretary_phone": secretary_phone, "note": note,
        })
        st.success("Карточка УК обновлена, касание записано в историю.")
        st.rerun()


def _render_contacts(card: dict[str, Any], state: dict[str, Any]) -> None:
    st.markdown("### Контакты")
    st.dataframe([{
        "Роль": role, "Значение": value or "—",
    } for role, value in (
        ("Компания", card["uk_name_short"]),
        ("Полное название", card["uk_name"]),
        ("ИНН", card["uk_inn"]),
        ("Адрес УК", card.get("uk_address")),
        ("Общий телефон УК", card.get("uk_phone")),
        ("Секретарь / диспетчер", state.get("secretary_phone")),
        ("Тех. контакт", state.get("exploitation_contact")),
        ("Телефон тех. контакта", state.get("tech_contact_phone")),
        ("Ответственный менеджер", card.get("responsible")),
    )], use_container_width=True, hide_index=True)


def render_uk_card(service: ObjectsService, key: str) -> None:
    """Render the detailed УК card: summary, next step, contacts and nested data."""
    if st.button("⬅ Вернуться к CRM-канбану УК"):
        st.session_state.pop("hydro_open_uk", None)
        st.rerun()
    state = latest_contour_state(key)
    parking_db = get_parking_db()
    db_ok = bool(parking_db.connect())
    if not db_ok:
        st.warning(f"База объектов недоступна: {parking_db.last_error}")
    row: dict[str, Any] = {}
    if db_ok:
        for candidate in fetch_uk_summary(parking_db, min_floors=0):
            if contour_key(candidate) == key:
                row = candidate
                break
    if not row and not state:
        st.error("Контур не найден: он не сохранён в CRM и отсутствует в базе объектов.")
        return
    card = build_card(row, state)
    ogrn = str(row.get("uk_ogrn") or state.get("uk_ogrn") or "").strip()
    object_rows: list[dict[str, Any]] = []
    if ogrn and db_ok:
        object_rows = fetch_map_objects(
            parking_db, MapFilters(min_floors=0, uk_status="DONE", uk_ogrn=ogrn, limit=2000)
        )
    tenders_615 = read_uk_summary(getattr(service, "crm_db", None), key)
    _render_summary(card, tenders_615)
    _render_status_form(key, card, state)
    _render_contacts(card, state)
    render_uk_crm_panel(getattr(service, "crm_db", None),
                        row.get("uk_inn") or card.get("uk_inn"),
                        card.get("uk_name") or card.get("uk_name_short"))
    _render_615(tenders_615)
    render_uk_activity(key, card, state, object_rows, ogrn or None)
