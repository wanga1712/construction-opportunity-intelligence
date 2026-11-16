"""Tab-specific content for the in-place Hydro UK manager workspace."""
from __future__ import annotations

import html
import re
from datetime import date, datetime, time
from typing import Any, Callable, Mapping

import streamlit as st

from src.services.hydro.company_repository import (
    ACTIVITY_STATUS_LABELS,
    ACTIVITY_TYPE_LABELS,
    RECEPTION_TYPE_LABELS,
    RECEPTION_TYPES,
    normalize_schedule,
    schedule_text,
)
from src.services.waterproofing_crm import CRM_STAGES, STAGE_DEFAULT_ACTIONS, normalize_stage

STATUS_FRESH = "fresh"
STATUS_STALE = "stale"

_RECEPTION_DAYS = (
    ("mon", "Понедельник", ("mon", "monday", "пн", "понедельник")),
    ("tue", "Вторник", ("tue", "tues", "tuesday", "вт", "вторник")),
    ("wed", "Среда", ("wed", "wednesday", "ср", "среда")),
    ("thu", "Четверг", ("thu", "thur", "thurs", "thursday", "чт", "четверг")),
    ("fri", "Пятница", ("fri", "friday", "пт", "пятница")),
    ("sat", "Суббота", ("sat", "saturday", "сб", "суббота")),
    ("sun", "Воскресенье", ("sun", "sunday", "вс", "воскресенье")),
)


def _reception_schedule_editor(label: str, value: Any, key: str) -> dict[str, str]:
    """Edit reception hours as weekday rows, separately from freeform notes."""
    schedule = normalize_schedule(value) or {}
    normalized = {str(day).strip().casefold(): str(hours).strip()
                  for day, hours in schedule.items() if str(hours).strip()}
    known_aliases = {alias for _, _, aliases in _RECEPTION_DAYS for alias in aliases}
    result: dict[str, str] = {
        str(day): str(hours) for day, hours in schedule.items()
        if str(day).strip().casefold() not in known_aliases and str(hours).strip()
    }
    st.markdown(f"**{label}**")
    for day_key, day_label, aliases in _RECEPTION_DAYS:
        hours = next((normalized[alias] for alias in aliases if alias in normalized), "")
        columns = st.columns([1, 3])
        enabled = columns[0].checkbox(
            day_label, value=bool(hours), key=f"{key}_{day_key}_enabled",
        )
        slot = columns[1].text_input(
            "Часы" if day_key == "mon" else f"Часы · {day_label}",
            value=hours, placeholder="09:00–18:00",
            key=f"{key}_{day_key}_hours", disabled=not enabled,
            label_visibility="collapsed" if day_key != "mon" else "visible",
        )
        if enabled and slot.strip():
            result[day_key] = slot.strip()
    return result


def short_address(value: Any) -> str:
    """Keep a compact street/house label while preserving source text as help."""
    text = " ".join(str(value or "").split())
    if not text:
        return "Адрес не указан"
    parts = [part.strip() for part in text.split(",") if part.strip()]
    street_index = next((i for i, part in enumerate(parts) if re.search(
        r"(?:^|\s)(?:ул\.?|улица|пр-т|проспект|пер\.?|проезд|б-р|шоссе)\s", part, re.I
    )), None)
    if street_index is not None:
        end = next((i for i in range(street_index, len(parts)) if re.search(
            r"(?:^|\s)(?:д\.?\s*)?\d+[А-Яа-яA-Za-z]?\s*$", parts[i], re.I
        )), None)
        if end is not None:
            result = parts[street_index:end + 1]
            if end + 1 < len(parts) and re.match(r"(?:корп\.?|стр\.?|к\.?|с\.?)\s*\S+", parts[end + 1], re.I):
                result.append(parts[end + 1])
            return ", ".join(result)
    return text if len(text) <= 74 else text[:71].rstrip() + "…"


def _contact_phones(contact: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    phones = contact.get("phones") or []
    if phones:
        return phones
    if contact.get("phone"):
        return [{"phone": contact.get("phone"), "extension": contact.get("phone_ext"),
                 "is_primary": True}]
    return []


def _phone_identity(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _render_phone_edit(repo: Any, company_id: int, phone_row: Mapping[str, Any],
                       contact_id: int | None, key: str) -> None:
    phone_id = phone_row.get("id")
    if phone_id is None:
        return
    with st.expander(f"Изменить телефон · {phone_row.get('label') or phone_row.get('phone')}", expanded=False):
        with st.form(f"hydro_phone_edit_{key}_{phone_id}"):
            phone = st.text_input("Телефон", value=str(phone_row.get("phone") or ""))
            left, right = st.columns(2)
            extension = left.text_input("Добавочный", value=str(phone_row.get("extension") or ""))
            phone_type = right.text_input("Тип", value=str(phone_row.get("phone_type") or "work"))
            label = st.text_input("Подпись", value=str(phone_row.get("label") or ""))
            primary = st.checkbox("Основной номер", value=bool(phone_row.get("is_primary")))
            comment = st.text_input("Комментарий", value=str(phone_row.get("comment") or ""))
            if st.form_submit_button("Сохранить телефон"):
                try:
                    ok = repo.update_contact_phone(phone_id, company_id, contact_id, {
                        "phone": phone, "extension": extension, "phone_type": phone_type,
                        "label": label, "is_primary": primary, "comment": comment,
                    })
                except Exception as exc:
                    st.error(f"Телефон не сохранён ({type(exc).__name__}).")
                    return
                if ok:
                    st.rerun()


def _render_contact_form(repo: Any, company: Mapping[str, Any], contact: Mapping[str, Any]) -> None:
    cid = int(company["id"])
    contact_id = int(contact["id"])
    with st.expander(f"Редактировать · {contact.get('full_name') or 'Контакт'}", expanded=False):
        with st.form(f"hydro_contact_edit_{cid}_{contact_id}"):
            full_name = st.text_input("ФИО", value=str(contact.get("full_name") or ""))
            role = st.text_input("Должность / роль", value=str(contact.get("role") or ""),
                                 placeholder="Например: главный инженер, начальник эксплуатации")
            left, right = st.columns(2)
            email = left.text_input("Email", value=str(contact.get("email") or ""))
            primary = right.checkbox("Основной контакт", value=bool(contact.get("is_primary")))
            phone_rows = _contact_phones(contact)
            for idx, number in enumerate(phone_rows, start=1):
                extension = f" доб. {number.get('extension')}" if number.get("extension") else ""
                st.caption(f"Телефон {idx}: {number.get('phone') or '—'}{extension} · {number.get('label') or number.get('phone_type') or ''}")
                _render_phone_edit(repo, cid, number, contact_id, f"contact_{contact_id}_{idx}")
            reception_options = ["", *RECEPTION_TYPES]
            current_reception = str(contact.get("reception_type") or "")
            reception_type = st.selectbox(
                "Приём этого контакта", reception_options,
                index=reception_options.index(current_reception) if current_reception in reception_options else 0,
                format_func=lambda key: RECEPTION_TYPE_LABELS.get(key, "Не задано") if key else "Не задано",
                key=f"hydro_contact_reception_type_{contact_id}",
            )
            reception_schedule = _reception_schedule_editor(
                "Часы приёма по дням", contact.get("reception_schedule"),
                f"hydro_contact_reception_schedule_{contact_id}",
            )
            reception_note = st.text_area(
                "Примечание по приёму", value=str(contact.get("reception_note") or ""),
                key=f"hydro_contact_reception_note_{contact_id}",
            )
            comment = st.text_area("Заметка о контакте", value=str(contact.get("comment") or ""))
            if st.form_submit_button("Сохранить контакт"):
                try:
                    ok = repo.update_contact(contact_id, {
                        "company_id": cid, "full_name": full_name, "role": role,
                        "email": email, "is_primary": primary, "comment": comment,
                        "phone": (phone_rows[0].get("phone") if phone_rows else contact.get("phone")),
                        "phone_ext": (phone_rows[0].get("extension") if phone_rows else contact.get("phone_ext")),
                        "reception_type": reception_type or None,
                        "reception_schedule": reception_schedule,
                        "reception_note": reception_note,
                    })
                except Exception as exc:
                    st.error(f"Контакт не сохранён: проверьте применение миграции полей приёма и телефонов ({type(exc).__name__}).")
                    return
                if ok:
                    st.rerun()
                st.error("Не удалось сохранить контакт.")


def _render_contact_add(repo: Any, company: Mapping[str, Any], contacts: list[dict[str, Any]]) -> None:
    cid = int(company["id"])
    with st.expander("+ Добавить контакт", expanded=False):
        with st.form(f"hydro_contact_add_{cid}"):
            full_name = st.text_input("ФИО")
            role = st.text_input("Должность / роль", placeholder="Главный инженер · начальник эксплуатации · секретарь · диспетчер")
            left, right = st.columns(2)
            phone = left.text_input("Телефон")
            extension = right.text_input("Добавочный")
            email = st.text_input("Email")
            reception_options = ["", *RECEPTION_TYPES]
            reception_type = st.selectbox(
                "Приём этого контакта", reception_options,
                format_func=lambda key: RECEPTION_TYPE_LABELS.get(key, "Не задано") if key else "Не задано",
            )
            reception_schedule = _reception_schedule_editor(
                "Часы приёма по дням", None, f"hydro_contact_add_schedule_{cid}",
            )
            reception_note = st.text_area("Примечание по приёму")
            primary = st.checkbox("Основной контакт", value=not contacts)
            if st.form_submit_button("Добавить контакт"):
                if not full_name.strip() or not role.strip():
                    st.error("Укажите ФИО и роль.")
                else:
                    phone_list = ([{"phone": phone, "extension": extension,
                                    "phone_type": "work", "label": "Основной", "is_primary": True}]
                                  if phone.strip() else [])
                    try:
                        repo.add_contact(cid, {
                            "full_name": full_name, "role": role, "phone": phone,
                            "phone_ext": extension, "email": email, "is_primary": primary,
                            "phones": phone_list, "reception_schedule": reception_schedule,
                            "reception_type": reception_type or None,
                            "reception_note": reception_note,
                        })
                    except Exception as exc:
                        st.error(f"Контакт не сохранён: проверьте применение миграции полей приёма и телефонов ({type(exc).__name__}).")
                    else:
                        st.rerun()


def _render_add_phone(repo: Any, company: Mapping[str, Any], contacts: list[dict[str, Any]]) -> None:
    cid = int(company["id"])
    with st.expander("+ Добавить телефон", expanded=False):
        contact_options = {"Телефон УК (общий)": None}
        contact_options.update({f"{c.get('full_name') or 'Контакт'} · {c.get('role') or 'роль не указана'}": int(c["id"])
                                for c in contacts})
        with st.form(f"hydro_phone_add_{cid}"):
            selected = st.selectbox("Кому принадлежит номер", list(contact_options))
            phone = st.text_input("Телефон")
            left, right = st.columns(2)
            extension = left.text_input("Добавочный")
            phone_type = right.text_input("Тип", value="work", placeholder="work, mobile, reception…")
            label = st.text_input("Подпись", placeholder="Секретарь, приёмная, аварийная линия")
            primary = st.checkbox("Основной номер")
            if st.form_submit_button("Сохранить телефон"):
                if not phone.strip():
                    st.error("Укажите номер телефона.")
                else:
                    try:
                        repo.add_contact_phone(cid, contact_options[selected], {
                            "phone": phone, "extension": extension,
                            "phone_type": phone_type, "label": label,
                            "is_primary": primary,
                        })
                    except Exception as exc:
                        st.error(f"Телефон не сохранён: проверьте применение миграции ({type(exc).__name__}).")
                    else:
                        st.rerun()


def render_contacts(repo: Any, company: Mapping[str, Any], card: Mapping[str, Any]) -> None:
    cid = int(company["id"])
    contacts = repo.list_contacts(cid)
    website = str(company.get("website") or "")
    phone = str(company.get("phone") or card.get("phone") or "")
    reception_options = ["", *RECEPTION_TYPES]
    current_reception = str(company.get("reception_type") or "")
    with st.form(f"hydro_company_contacts_{cid}"):
        website_value = st.text_input("Сайт УК", value=website, placeholder="https://…")
        phone_value = st.text_input("Общий телефон", value=phone)
        reception_type = st.selectbox(
            "Приём УК", reception_options,
            index=reception_options.index(current_reception) if current_reception in reception_options else 0,
            format_func=lambda key: RECEPTION_TYPE_LABELS.get(key, "Не задано") if key else "Не задано",
        )
        reception_schedule = _reception_schedule_editor(
            "График приёма УК", company.get("reception_schedule"),
            f"hydro_company_reception_schedule_{cid}",
        )
        if st.form_submit_button("Сохранить данные УК"):
            repo.save_params(cid, {
                "website": website_value, "phone": phone_value,
                "reception_type": reception_type or None,
                "reception_schedule": reception_schedule,
            })
            st.rerun()
    try:
        company_phones = repo.list_company_phones(cid)
    except Exception:
        company_phones = []
    company_phone_id = _phone_identity(phone)
    company_phones = [row for row in company_phones
                      if not company_phone_id or _phone_identity(row.get("phone")) != company_phone_id]
    if company_phones:
        st.caption("Дополнительные телефоны УК: " + " · ".join(
            f"{row.get('phone')}{(' доб. ' + str(row.get('extension'))) if row.get('extension') else ''}"
            for row in company_phones
        ))
        for index, phone_row in enumerate(company_phones, start=1):
            _render_phone_edit(repo, cid, phone_row, None, f"company_{cid}_{index}")
    for contact in contacts:
        role = html.escape(str(contact.get("role") or "Роль не указана"))
        name = html.escape(str(contact.get("full_name") or "Контакт"))
        st.markdown(f"**{name}** · {role}")
        numbers = _contact_phones(contact)
        if numbers:
            st.caption(" · ".join(
                f"{n.get('phone') or '—'}{(' доб. ' + str(n.get('extension'))) if n.get('extension') else ''}"
                for n in numbers
            ))
        if contact.get("email"):
            st.caption(str(contact["email"]))
        _render_contact_form(repo, company, contact)
    _render_contact_add(repo, company, contacts)
    _render_add_phone(repo, company, contacts)


def render_objects(repo: Any, company: Mapping[str, Any], uk_key: str = "") -> None:
    objects = repo.list_objects(int(company["id"]))
    if not objects:
        st.info("У этой УК пока нет связанных объектов.")
        return
    if uk_key:
        from src.services.waterproofing_615_store import read_uk_contract_rows
        from src.services.waterproofing_615 import address_key
        payload = read_uk_contract_rows(repo.db, uk_key)
    else:
        address_key = lambda _: None
        payload = {"available": False, "rows": []}
    if not payload.get("available"):
        st.caption("615-ПП: состояние связи недоступно")
    elif payload.get("status") == STATUS_STALE:
        st.caption("615-ПП: показан последний сохранённый срез; отсутствие связи не подтверждено")
    elif payload.get("status") != STATUS_FRESH:
        st.caption(str(payload.get("message") or "615-ПП: синхронизация ещё не завершена"))
    rows_by_key: dict[str, list[dict[str, Any]]] = {}
    for row in payload.get("rows") or []:
        rows_by_key.setdefault(str(row.get("address_key") or ""), []).append(row)

    for item in objects:
        address = str(item.get("address") or "")
        st.markdown(f"**{short_address(address)}**", help=address or None)
        details = []
        floors = item.get("floors_underground")
        if floors is not None:
            details.append(f"{floors} подземных этажей")
        details.append(str(item.get("parking_type") or item.get("object_type") or "Тип не указан"))
        spaces = item.get("parking_spaces")
        if spaces is not None:
            details.append(f"парковочных мест: {spaces}")
        if item.get("management_status"):
            details.append(f"статус: {item['management_status']}")
        elif item.get("inspection_done"):
            details.append("обследование проведено")
        parts = address_key(address)
        normalized = f"{parts[0]} {parts[1]}" if parts else ""
        linked = [row for row in rows_by_key.get(normalized, []) if row.get("contract_id")]
        if linked:
            details.append(f"615-ПП: найдено {len(linked)} контракт(а/ов)")
        elif payload.get("available") and payload.get("status") == STATUS_FRESH:
            details.append("615-ПП: не найдено")
        else:
            details.append("615-ПП: неизвестно")
        st.caption(" · ".join(details))
        st.divider()


def _contract_groups(
    payload: Mapping[str, Any],
    objects: list[dict[str, Any]],
    address_key_fn: Callable[[Any], Any] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    if address_key_fn is None:
        from src.services.waterproofing_615 import address_key as address_key_fn
    rows = payload.get("rows") or []
    rows_by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_key.setdefault(str(row.get("address_key") or ""), []).append(row)
    grouped: dict[str, list[dict[str, Any]]] = {}
    matched_objects = 0
    for obj in objects:
        parts = address_key_fn(obj.get("address"))
        normalized = f"{parts[0]} {parts[1]}" if parts else ""
        linked = rows_by_key.get(normalized, [])
        if linked:
            matched_objects += 1
        grouped[str(obj.get("address") or "Адрес не указан")] = linked
    return grouped, matched_objects


def contract_summary(payload: Mapping[str, Any], object_count: int,
                     matched_objects: int) -> dict[str, Any] | None:
    """Return totals only when the persisted sync state supports an honest total."""
    if not payload.get("available") or payload.get("status") not in (STATUS_FRESH, STATUS_STALE):
        return None
    rows = payload.get("rows") or []
    contracts = [row for row in rows if row.get("contract_id")]
    if payload.get("status") == STATUS_STALE and not contracts:
        return None
    return {
        "contracts": len(contracts), "objects": int(object_count),
        "matched_objects": int(matched_objects),
        "amount": sum(float(row.get("amount") or 0) for row in contracts),
    }


def contract_detail_line(row: Mapping[str, Any]) -> str:
    date_value = row.get("contract_date")
    year = row.get("contract_year") or (getattr(date_value, "year", None) or "—")
    amount = float(row.get("amount") or 0)
    method = row.get("match_method") or row.get("address_match_method") or "—"
    score = row.get("match_score")
    if score is None:
        score = row.get("address_match_score")
    confidence = f"{float(score) * 100:.0f}%" if score is not None else "—"
    return (
        f"№ {row.get('contract_number') or row.get('contract_id')} · {date_value or year} · "
        f"{amount:,.0f} ₽ · гидроизоляция: {'да' if row.get('is_waterproofing') else 'нет'} · "
        f"{method} / {confidence}"
    ).replace(",", " ")


def dispatch_workspace_tab(selected: str, labels: list[str], handlers: Mapping[str, Callable[[], None]]) -> None:
    """Run the selected tab renderer only; Streamlit's st.tabs eagerly runs all tabs."""
    if selected in labels and selected in handlers:
        handlers[selected]()


def render_615(repo: Any, company: Mapping[str, Any], uk_key: str) -> None:
    from src.services.waterproofing_615_store import read_uk_contract_rows

    payload = read_uk_contract_rows(repo.db, uk_key)
    if not payload.get("available"):
        st.warning(str(payload.get("message") or "Связка 615-ПП недоступна."))
        return
    if payload.get("status") == STATUS_STALE:
        st.warning(str(payload.get("message") or "Связка 615-ПП устарела; показанные строки — последний сохранённый срез."))
    elif payload.get("status") != STATUS_FRESH:
        st.info(str(payload.get("message") or "Синхронизация 615-ПП ещё не завершена."))
        return
    if payload.get("status") == STATUS_STALE and not payload.get("rows"):
        st.caption("Сохранённый срез пуст; актуальное число контрактов и сумма неизвестны.")
        return
    objects = repo.list_objects(int(company["id"]))
    grouped, matched_objects = _contract_groups(payload, objects)
    rows = payload.get("rows") or []
    object_count = len(objects)
    totals = contract_summary(payload, object_count, matched_objects)
    if totals is None:
        st.caption("Синхронизация не позволяет достоверно показать итоги по контрактам.")
        return
    st.markdown(f"**Найдено {totals['contracts']} контрактов по {matched_objects} из {object_count} объектов**")
    st.markdown(f"Общая сумма: **{totals['amount']:,.0f} ₽**".replace(",", " "))
    if not rows:
        st.info("Свежий срез 615-ПП не содержит связанных адресов.")
        return
    if not grouped:
        st.info("Свежий срез 615-ПП не содержит связанных объектов по этим адресам.")
        return
    for address, address_rows in grouped.items():
        st.markdown(f"#### {short_address(address)}")
        if not address_rows or not any(row.get("contract_id") for row in address_rows):
            st.caption("По этому адресу связь с 615-ПП не найдена")
            continue
        for row in address_rows:
            if not row.get("contract_id"):
                continue
            st.caption(contract_detail_line(row))


def _activity_form(repo: Any, company_id: int, activity_type: str, label: str) -> None:
    with st.expander(label, expanded=False):
        with st.form(f"hydro_activity_{company_id}_{activity_type}"):
            title = st.text_input("Тема", value=label)
            left, right = st.columns(2)
            when_date = left.date_input("Дата", value=date.today())
            when_time = right.time_input("Время", value=time(11, 0))
            description = st.text_area("Комментарий")
            if st.form_submit_button("Запланировать"):
                start = datetime.combine(when_date, when_time)
                repo.add_activity(company_id, {
                    "activity_type": activity_type, "title": title,
                    "description": description, "start_time": start,
                    "status": "planned",
                })
                st.rerun()


def render_actions(
    repo: Any,
    company: Mapping[str, Any],
    card: Mapping[str, Any],
    move_stage: Callable[[str], Mapping[str, Any]],
) -> None:
    current = normalize_stage(card.get("stage"))
    current_label = current
    st.markdown(f"**Текущий этап:** {current_label}")
    st.markdown(f"**Следующий шаг:** {card.get('next_action') or STAGE_DEFAULT_ACTIONS.get(current, '—')}")
    try:
        contacts = repo.list_contacts(int(company["id"]))
    except Exception:
        contacts = []
    key_roles = {"главный инженер", "начальник эксплуатации", "секретарь", "диспетчер"}
    for contact in contacts:
        if str(contact.get("role") or "").strip().casefold() in key_roles and contact.get("reception_schedule"):
            st.caption(f"Приём · {contact.get('role')}: {schedule_text(contact.get('reception_schedule'))}")
    stage_ids = list(CRM_STAGES)
    selected_stage = st.selectbox(
        "Перевести на этап", stage_ids,
        index=stage_ids.index(current) if current in stage_ids else 0,
        format_func=lambda key: key,
        key=f"hydro_overlay_stage_{card.get('key')}",
    )
    if st.button("Сохранить этап", key=f"hydro_overlay_stage_save_{card.get('key')}",
                 disabled=selected_stage == current):
        result = move_stage(selected_stage)
        if result.get("moved"):
            st.rerun()
        st.warning(f"Этап не изменён: {result.get('reason') or 'повторите действие'}.")

    cid = int(company["id"])
    _activity_form(repo, cid, "call", "Запланировать звонок")
    _activity_form(repo, cid, "meeting", "Назначить встречу")
    _activity_form(repo, cid, "inspection", "Назначить обследование")
    activities = repo.list_activities(cid, limit=15)
    next_item = next((item for item in activities if item.get("status") == "planned"), None)
    if next_item:
        st.caption(f"Ближайшее: {next_item.get('title') or ACTIVITY_TYPE_LABELS.get(next_item.get('activity_type'), 'Действие')} · {next_item.get('start_time')}")
    st.markdown("**История действий**")
    if not activities:
        st.caption("История пока пуста.")
        return
    for item in activities:
        stamp = item.get("start_time") or item.get("created_at")
        status = ACTIVITY_STATUS_LABELS.get(item.get("status"), item.get("status") or "")
        kind = ACTIVITY_TYPE_LABELS.get(item.get("activity_type"), item.get("activity_type") or "Действие")
        st.caption(f"{stamp} · {kind} · {item.get('title') or ''} · {status}")


__all__ = [
    "contract_detail_line", "contract_summary", "dispatch_workspace_tab", "short_address",
    "render_actions", "render_contacts", "render_objects", "render_615",
]
