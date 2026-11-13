"""Editable manager workspace embedded in the existing waterproofing UK card."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import streamlit as st

from src.services.hydro import company_repository as cr
from src.services.hydro.company_repository import HydroCompanyRepository
from src.services.hydro.card_repository import HydroCardRepository, effective

_DAYS = (("mon", "Понедельник"), ("tue", "Вторник"), ("wed", "Среда"),
         ("thu", "Четверг"), ("fri", "Пятница"), ("sat", "Суббота"),
         ("sun", "Воскресенье"))
_ZONES = ("Общий вид", "Фасад", "Въезд", "Паркинг", "Потолок / перекрытие",
          "Стена", "Колонна", "Шов", "Другая зона")
_DEFECTS = ("Протечка", "Трещина", "Высолы", "Шов", "Следы ремонта",
            "Следы инъектирования", "Разрушение бетона", "Коррозия", "Влажность", "Другое")


def _schedule_map(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = cr.normalize_schedule(value)
    aliases = {"пн": "mon", "вт": "tue", "ср": "wed", "чт": "thu",
               "пт": "fri", "сб": "sat", "вс": "sun"}
    result = {}
    for key, slot in (value or {}).items():
        day = str(key).lower()
        if day in ("_role", "role"):
            continue
        day = aliases.get(day[:2], day[:3])
        if day in dict(_DAYS) and slot:
            result[day] = str(slot)
    return result


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime) and value.tzinfo:
        return value.astimezone().replace(tzinfo=None)
    return value if isinstance(value, datetime) else None


def _contact_form(repo: HydroCompanyRepository, company_id: int, item: dict[str, Any] | None = None) -> None:
    editing = item is not None
    title = "Редактировать контакт" if editing else "Добавить контакт"
    with st.expander(title, expanded=not editing):
        with st.form(f"hydro_contact_{company_id}_{item.get('id') if item else 'new'}"):
            a, b = st.columns(2)
            full_name = a.text_input("ФИО *", value=str((item or {}).get("full_name") or ""))
            role = b.text_input("Должность / роль *", value=str((item or {}).get("role") or ""),
                                placeholder="Секретарь, диспетчер, главный инженер")
            phone = a.text_input("Телефон", value=str((item or {}).get("phone") or ""))
            phone_ext = b.text_input("Дополнительный телефон", value=str((item or {}).get("phone_ext") or ""))
            email = a.text_input("Email", value=str((item or {}).get("email") or ""))
            comment = b.text_input("Комментарий / источник", value=str((item or {}).get("comment") or ""))
            primary = st.checkbox("Основной контакт", value=bool((item or {}).get("is_primary")))
            save, cancel = st.columns(2)
            submitted = save.form_submit_button("Сохранить", type="primary")
            cancelled = cancel.form_submit_button("Отмена")
            if cancelled:
                st.rerun()
            if submitted:
                values = {"full_name": full_name, "role": role, "phone": phone,
                          "phone_ext": phone_ext, "email": email, "comment": comment,
                          "is_primary": primary, "company_id": company_id}
                ok = False
                if full_name.strip() and role.strip():
                    ok = (repo.update_contact(item["id"], values) if editing else
                          repo.add_contact(company_id, values))
                if ok:
                    st.success("Контакт сохранён.")
                    st.rerun()
                st.error("Укажите роль и ФИО контакта; телефон можно добавить отдельно.")


def _contacts(repo: HydroCompanyRepository, company_id: int, company: dict[str, Any]) -> list[dict[str, Any]]:
    st.markdown("#### Контакты")
    st.caption(f"Общий телефон УК: {company.get('phone') or 'не указан'}")
    contacts = repo.list_contacts(company_id)
    for item in contacts:
        with st.container(border=True):
            st.markdown(f"**{item.get('full_name') or item.get('phone') or 'Контакт'}** · {item.get('role') or 'роль не указана'}")
            st.caption(" · ".join(str(x) for x in (item.get("phone"), item.get("email"), item.get("comment")) if x) or "Детали не заполнены")
            _contact_form(repo, company_id, item)
    if not contacts:
        st.info("Контакты не заполнены. Добавьте секретаря, диспетчера или технический контакт.")
    _contact_form(repo, company_id)
    return contacts


def _schedule(repo: HydroCompanyRepository, company: dict[str, Any]) -> tuple[dict[str, str], str]:
    st.markdown("#### График приёма · еженедельно")
    schedule = _schedule_map(company.get("reception_schedule"))
    raw_schedule = company.get("reception_schedule") or {}
    if isinstance(raw_schedule, str):
        try:
            raw_schedule = json.loads(raw_schedule)
        except ValueError:
            raw_schedule = cr.normalize_schedule(raw_schedule) or {}
    role_label = str(raw_schedule.get("_role") or raw_schedule.get("role") or "") if isinstance(raw_schedule, dict) else ""
    if schedule:
        st.caption(" · ".join(f"{dict(_DAYS).get(day, day)} {slot}" for day, slot in schedule.items()))
    else:
        st.info("График приёма не заполнен.")
    with st.expander("Заполнить / изменить график"):
        with st.form(f"hydro_schedule_{company['id']}"):
            role = st.text_input("Контакт или роль", value="Главный инженер")
            values: dict[str, str] = {}
            for code, label in _DAYS:
                cols = st.columns([2, 1, 1])
                enabled = cols[0].checkbox(label, value=code in schedule, key=f"hydro_day_{company['id']}_{code}")
                old = schedule.get(code, "")
                start, end = (old.split("-", 1) + [""])[:2] if old else ("", "")
                start_time = cols[1].text_input("С", value=start[:5], key=f"hydro_start_{company['id']}_{code}", placeholder="14:00")
                end_time = cols[2].text_input("До", value=end[:5], key=f"hydro_end_{company['id']}_{code}", placeholder="17:00")
                if enabled and start_time and end_time:
                    values[code] = f"{start_time}-{end_time}"
            save, cancel = st.columns(2)
            submitted = save.form_submit_button("Сохранить график", type="primary")
            cancelled = cancel.form_submit_button("Отмена")
            if cancelled:
                st.rerun()
            if submitted:
                if values and not role.strip():
                    st.error("Укажите контакт или роль, для кого действует график.")
                else:
                    values["_role"] = role.strip()
                    repo.save_params(company["id"], {"reception_schedule": values})
                    st.success(f"График приёма {role.strip() or 'контакта'} сохранён.")
                    st.rerun()
    return schedule, role_label


def _calendar(repo: HydroCompanyRepository, company_id: int, schedule: dict[str, str],
              objects: list[dict[str, Any]], contacts: list[dict[str, Any]], schedule_role: str = "") -> None:
    st.markdown("#### Календарь взаимодействий")
    offset = int(st.session_state.get(f"hydro_week_offset_{company_id}", 0))
    nav_l, title, nav_r = st.columns([1, 5, 1])
    if nav_l.button("← Предыдущая", key=f"hydro_week_prev_{company_id}"):
        st.session_state[f"hydro_week_offset_{company_id}"] = offset - 1
        st.rerun()
    monday = date.today() - timedelta(days=date.today().weekday()) + timedelta(weeks=offset)
    title.markdown(f"**{monday:%d.%m.%Y} – {(monday + timedelta(days=6)):%d.%m.%Y}**")
    if nav_r.button("Следующая →", key=f"hydro_week_next_{company_id}"):
        st.session_state[f"hydro_week_offset_{company_id}"] = offset + 1
        st.rerun()
    activities = [a for a in repo.list_activities(company_id) if a.get("status") == "planned"]
    contact_names = {int(c["id"]): c.get("full_name") for c in contacts}
    cols = st.columns(7, gap="small")
    for idx, col in enumerate(cols):
        day = monday + timedelta(days=idx)
        code = _DAYS[idx][0]
        col.markdown(f"**{'🔵 ' if day == date.today() else ''}{_DAYS[idx][1][:2]} {day:%d.%m}**")
        slot = schedule.get(code)
        if slot:
            col.caption(f"{slot}\nПриём{(': ' + schedule_role) if schedule_role else ''}")
        todays = []
        for activity in activities:
            value = _as_datetime(activity.get("start_time"))
            if isinstance(value, datetime) and value.date() == day:
                todays.append((value, activity))
        for value, item in todays:
            contact = contact_names.get(item.get("contact_id"))
            col.caption(f"{value:%H:%M} · {item.get('title') or cr.ACTIVITY_TYPE_LABELS.get(item.get('activity_type'), 'Действие')}"
                        f"{(' · ' + str(contact)) if contact else ''}")
    st.markdown("**Запланировать действие**")
    upcoming = sorted((( _as_datetime(a.get("start_time")), a) for a in activities),
                      key=lambda pair: pair[0] or datetime.max)
    upcoming = [(when, activity) for when, activity in upcoming if when and when >= datetime.now()]
    if upcoming:
        when, nearest = upcoming[0]
        st.info(f"Ближайшее действие: {when:%d.%m.%Y %H:%M} · {nearest.get('title') or 'Действие'}")
    else:
        st.caption("Следующий шаг не назначен.")
    actions = st.columns(4)
    for column, kind, label in zip(actions, ("meeting", "call", "inspection", "follow_up"),
                                   ("Назначить встречу", "Запланировать звонок", "Назначить обследование", "Добавить задачу")):
        if column.button(label, key=f"hydro_event_btn_{company_id}_{kind}"):
            st.session_state[f"hydro_event_form_{company_id}"] = kind
    kind = st.session_state.get(f"hydro_event_form_{company_id}")
    if kind:
        with st.form(f"hydro_event_form_{company_id}_{kind}"):
            options = [None, *[int(o["id"]) for o in objects]]
            address = {int(o["id"]): o.get("address") or o.get("cadastral_number") for o in objects}
            object_id = st.selectbox("Объект", options, format_func=lambda x: "УК в целом" if x is None else str(address.get(x, x)))
            when_date = st.date_input("Дата", value=date.today())
            when_time = st.time_input("Время", value=time(10, 0))
            duration = st.number_input("Продолжительность, минут", min_value=15, max_value=480, value=60, step=15)
            contact_id = st.selectbox("Контакт", [None, *[int(c["id"]) for c in contacts]],
                                      format_func=lambda x: "Не выбран" if x is None else next(c.get("full_name") or "Контакт" for c in contacts if int(c["id"]) == x))
            title_value = st.text_input("Тема", value=cr.ACTIVITY_TYPE_LABELS.get(kind, "Задача"))
            description = st.text_area("Комментарий")
            if kind == "inspection" and not objects:
                st.error("Для обследования сначала требуется конкретный объект.")
            save, cancel = st.columns(2)
            submitted = save.form_submit_button("Сохранить", type="primary")
            cancelled = cancel.form_submit_button("Отмена")
            if cancelled:
                st.session_state.pop(f"hydro_event_form_{company_id}", None)
                st.rerun()
            if submitted:
                if kind == "inspection" and object_id is None:
                    st.error("Для обследования выберите объект.")
                else:
                    start = datetime.combine(when_date, when_time)
                    repo.add_activity(company_id, {"activity_type": kind, "title": title_value,
                        "description": description, "start_time": start,
                        "end_time": start + timedelta(minutes=int(duration)), "object_id": object_id,
                        "contact_id": contact_id})
                    st.session_state.pop(f"hydro_event_form_{company_id}", None)
                    st.success("Действие сохранено.")
                    st.rerun()


def render_object_photo_fixation(db: Any, obj: dict[str, Any]) -> None:
    """Display and append photo evidence in the existing Hydro object JSONB authority."""
    effective_photos, _ = effective(obj, "inspection_photos")
    photos = effective_photos or []
    if isinstance(photos, str):
        try:
            photos = json.loads(photos)
        except ValueError:
            photos = []
    if not isinstance(photos, list):
        photos = []
    if photos:
        cols = st.columns(min(4, len(photos)))
        for col, photo in zip(cols, photos[-4:]):
            path = photo.get("path") if isinstance(photo, dict) else None
            if path and Path(path).is_file():
                col.image(path, caption=photo.get("comment") or photo.get("zone"), use_container_width=True)
        for photo in photos:
            if isinstance(photo, dict):
                st.caption(" · ".join(str(x) for x in (photo.get("created_at"), photo.get("zone"),
                    ", ".join(photo.get("defect_tags") or []), photo.get("comment")) if x))
    else:
        st.caption("Фото объекта отсутствуют.")
    with st.expander(f"Фотофиксация · {len(photos)} фото"):
        with st.form(f"hydro_photo_{obj['id']}"):
            uploaded = st.file_uploader("Добавить фото", type=["jpg", "jpeg", "png", "webp"], key=f"hydro_photo_file_{obj['id']}")
            zone = st.selectbox("Зона", _ZONES, key=f"hydro_photo_zone_{obj['id']}")
            tags = st.multiselect("Дефекты", _DEFECTS, key=f"hydro_photo_tags_{obj['id']}")
            comment = st.text_input("Комментарий", key=f"hydro_photo_comment_{obj['id']}")
            save, cancel = st.columns(2)
            submitted = save.form_submit_button("Сохранить фото", type="primary")
            cancelled = cancel.form_submit_button("Отмена")
            if cancelled:
                st.rerun()
            if submitted:
                if not uploaded:
                    st.error("Выберите изображение.")
                else:
                    folder = Path("data/waterproofing/object_photos") / str(obj["id"])
                    folder.mkdir(parents=True, exist_ok=True)
                    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", uploaded.name)
                    filename = f"{datetime.now():%Y%m%d%H%M%S}_{safe_name}"
                    path = (folder / filename).resolve()
                    path.write_bytes(uploaded.getvalue())
                    photos.append({"path": str(path), "created_at": datetime.now().isoformat(timespec="seconds"),
                        "created_by": str(st.session_state.get("user_email") or st.session_state.get("username") or "unknown"),
                        "comment": comment, "zone": zone, "defect_tags": tags})
                    HydroCardRepository(db).save_overrides(int(obj["id"]), {"inspection_photos": photos})
                    st.success("Фото сохранено.")
                    st.rerun()


def _address_key(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _objects(repo: HydroCompanyRepository, company_id: int, tenders_615: dict[str, Any] | None = None) -> None:
    st.markdown("#### Объекты УК")
    objects = repo.list_objects(company_id)
    if not objects:
        st.info("Связанные Hydro объекты не найдены.")
        return
    count_parking = sum(bool(o.get("parking_type")) for o in objects)
    source_matches = { _address_key(m.get("address")): m for m in (tenders_615 or {}).get("matches", []) }
    count_615 = sum(_address_key(o.get("address")) in source_matches for o in objects)
    count_procurement = sum(bool(o.get("tender_number")) for o in objects)
    st.caption(f"Все {len(objects)} · паркинг {count_parking} · 615-ПП {count_615} · закупки {count_procurement}")
    filter_key = f"hydro_object_filter_{company_id}"
    selected_filter = st.radio("Фильтр объектов", ("Все", "С паркингом", "615-ПП", "Закупки"),
                               horizontal=True, key=filter_key, label_visibility="collapsed")
    if selected_filter == "С паркингом":
        objects = [o for o in objects if o.get("parking_type")]
    elif selected_filter == "615-ПП":
        objects = [o for o in objects if _address_key(o.get("address")) in source_matches]
    elif selected_filter == "Закупки":
        objects = [o for o in objects if o.get("tender_number")]
    show_all = st.toggle("Показать все объекты", key=f"hydro_objects_all_{company_id}")
    for obj in (objects if show_all else objects[:10]):
        with st.container(border=True):
            st.markdown(f"**{obj.get('address') or 'Адрес не указан'}**")
            details = []
            if obj.get("floors_underground") is not None:
                details.append(f"Подземных этажей: {obj['floors_underground']}")
            if obj.get("parking_type"):
                details.append(f"Паркинг: {obj['parking_type']}")
            if obj.get("tender_number"):
                details.append(f"Связанная закупка: {obj['tender_number']}")
            if obj.get("tender_nmck") is not None:
                details.append(f"НМЦК: {obj['tender_nmck']}")
            match = source_matches.get(_address_key(obj.get("address")))
            if match:
                details.append(f"615-ПП ✓ · торгов {match.get('tenders')} · {match.get('amount_label')}")
            st.caption(" · ".join(details) if details else "Данные паркинга или 615-ПП отсутствуют")
            render_object_photo_fixation(repo.db, obj)
            if st.button("Открыть полную карточку объекта", key=f"hydro_obj_full_{obj['id']}"):
                st.session_state.pop("hydro_open_uk", None)
                st.session_state["hydro_open_object"] = int(obj["id"])
                st.session_state["hydro_screen"] = "🅿️ Паркинги и объекты (карточки)"
                st.rerun()


def render_uk_workspace(repo: HydroCompanyRepository, company: dict[str, Any],
                        tenders_615: dict[str, Any] | None = None) -> None:
    """Render contacts, recurring reception, current week and linked Hydro objects."""
    left, center, right = st.columns([0.85, 2.45, 1.35], gap="small")
    with left:
        contacts = _contacts(repo, int(company["id"]), company)
        schedule, schedule_role = _schedule(repo, company)
    objects = repo.list_objects(company["id"])
    with center:
        _calendar(repo, int(company["id"]), schedule, objects, contacts, schedule_role)
    with right:
        _objects(repo, int(company["id"]), tenders_615)
