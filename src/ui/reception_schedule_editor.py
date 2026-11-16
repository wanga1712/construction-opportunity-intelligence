"""Shared compact editor and display helpers for reception schedules."""
from __future__ import annotations

import re
from datetime import time
from typing import Any, Mapping

import streamlit as st

from src.services.hydro.company_repository import RECEPTION_TYPE_LABELS

DAYS = (
    ("mon", "Пн", ("mon", "monday", "пн", "понедельник")),
    ("tue", "Вт", ("tue", "tues", "tuesday", "вт", "вторник")),
    ("wed", "Ср", ("wed", "wednesday", "ср", "среда")),
    ("thu", "Чт", ("thu", "thur", "thurs", "thursday", "чт", "четверг")),
    ("fri", "Пт", ("fri", "friday", "пт", "пятница")),
)
_LEGACY_WEEKEND_DAYS = (
    ("sat", ("sat", "saturday", "сб", "суббота")),
    ("sun", ("sun", "sunday", "вс", "воскресенье")),
)
DAY_LABELS = {key: label for key, label, _ in DAYS}
_TIME_RANGE = re.compile(r"^\s*(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})\s*$")


def _valid_time(value: Any) -> str | None:
    text = str(value or "").strip()
    try:
        hour, minute = (int(part) for part in text.split(":", 1))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    except (TypeError, ValueError):
        pass
    return None


def normalize_weekly_schedule(raw: Any) -> tuple[dict[str, Any], str | None]:
    """Read canonical JSON and legacy text/maps without discarding unknown data."""
    if raw in (None, ""):
        return {}, None
    schedule: dict[str, Any] = {}
    legacy_parts: list[str] = []
    aliases = {alias: key for key, _, names in DAYS for alias in names}
    aliases.update({alias: key for key, names in _LEGACY_WEEKEND_DAYS for alias in names})

    def add(day_name: Any, slot: Any) -> None:
        day = aliases.get(str(day_name).strip().casefold())
        if not day:
            legacy_parts.append(f"{day_name}: {slot}".strip(": "))
            return
        if isinstance(slot, Mapping):
            start = _valid_time(slot.get("from", slot.get("start")))
            end = _valid_time(slot.get("to", slot.get("end")))
        else:
            match = _TIME_RANGE.match(str(slot or ""))
            start, end = (_valid_time(match.group(1)), _valid_time(match.group(2))) if match else (None, None)
        if start and end:
            schedule[day] = {"from": start, "to": end}
        elif slot not in (None, "", False):
            legacy_parts.append(f"{day_name}: {slot}".strip(": "))

    if isinstance(raw, Mapping):
        for day, slot in raw.items():
            if str(day) == "_legacy":
                if slot:
                    legacy_parts.append(str(slot))
            elif isinstance(slot, Mapping) and slot.get("enabled") is False:
                continue
            else:
                add(day, slot)
    else:
        for chunk in re.split(r"[;\n]+", str(raw).strip()):
            chunk = chunk.strip()
            if not chunk:
                continue
            match = re.match(r"^([^:=—]+?)\s*(?:=|:|—|\s)\s*(.+)$", chunk)
            if match:
                day_name = match.group(1).strip()
                if day_name.casefold() in aliases:
                    add(day_name, match.group(2))
                else:
                    legacy_parts.append(chunk)
            else:
                legacy_parts.append(chunk)
    return schedule, "; ".join(legacy_parts) or None


def reception_type_label(value: Any) -> str:
    return RECEPTION_TYPE_LABELS.get(str(value or "daily"), "Живая очередь")


def format_compact_schedule(raw: Any, reception_type: Any = "daily") -> str:
    schedule, legacy = normalize_weekly_schedule(raw)
    weekday_keys = [key for key, _, _ in DAYS]
    if legacy and not any(schedule.get(day) for day in weekday_keys):
        return f"Старый график: {legacy}"
    if not any(schedule.get(day) for day in weekday_keys):
        return "График не задан"
    rows = []
    day_order = weekday_keys
    index = 0
    while index < len(day_order):
        day = day_order[index]
        slot = schedule.get(day)
        end = index
        while end + 1 < len(day_order) and schedule.get(day_order[end + 1]) == slot:
            end += 1
        span = DAY_LABELS[day] if end == index else f"{DAY_LABELS[day]}–{DAY_LABELS[day_order[end]]}"
        value = f"{slot['from']}–{slot['to']}" if slot else "выходной"
        if slot or str(reception_type or "daily") != "scheduled":
            rows.append(f"{span}　{value}")
        index = end + 1
    if legacy:
        rows.append(f"Старый график: {legacy}")
    return "\n".join(rows) if rows else "График не задан"


def validate_weekly_schedule(schedule: Mapping[str, Any]) -> str | None:
    for day in schedule.values():
        if not isinstance(day, Mapping):
            continue
        start = _valid_time(day.get("from"))
        end = _valid_time(day.get("to"))
        if not start or not end:
            return "Укажите время начала и окончания для каждого выбранного дня."
        if start >= end:
            return "Время окончания должно быть позже времени начала."
    return None


def apply_weekday_shortcut(schedule: Mapping[str, Any], start: Any, end: Any) -> dict[str, Any]:
    """Apply a selected interval to Monday-Friday while preserving hidden legacy data."""
    start_text = start.strftime("%H:%M") if hasattr(start, "strftime") else _valid_time(start)
    end_text = end.strftime("%H:%M") if hasattr(end, "strftime") else _valid_time(end)
    result = dict(schedule)
    if start_text and end_text:
        for day_key, _, _ in DAYS[:5]:
            result[day_key] = {"from": start_text, "to": end_text}
    return result


def render_reception_schedule_editor(
    prefix: str, reception_type: str | None, reception_schedule: Any,
) -> tuple[str, dict[str, Any], str | None, bool]:
    """Render shared reception type and weekly time-picker controls."""
    schedule, legacy = normalize_weekly_schedule(reception_schedule)
    type_value = str(reception_type or "daily")
    if type_value not in RECEPTION_TYPE_LABELS:
        type_value = "daily"
    reception_type = st.radio(
        "Тип приёма", tuple(RECEPTION_TYPE_LABELS), horizontal=True,
        format_func=lambda value: RECEPTION_TYPE_LABELS[value],
        index=tuple(RECEPTION_TYPE_LABELS).index(type_value), key=f"{prefix}_type",
    )
    if legacy:
        st.warning(f"Старый график: {legacy}. Разобранные дни сохранены; старые данные будут сохранены.")

    quick_prefix = f"{prefix}_weekdays"
    quick_start, quick_end, apply = st.columns([1, 1, 2])
    quick_start.time_input("Будни с", value=time(9, 0), key=f"{quick_prefix}_from")
    quick_end.time_input("Будни до", value=time(18, 0), key=f"{quick_prefix}_to")

    def apply_weekdays() -> None:
        start_value = st.session_state.get(f"{quick_prefix}_from", time(9, 0))
        end_value = st.session_state.get(f"{quick_prefix}_to", time(18, 0))
        filled = apply_weekday_shortcut({}, start_value, end_value)
        for key, _, _ in DAYS[:5]:
            st.session_state[f"{prefix}_{key}_enabled"] = True
            st.session_state[f"{prefix}_{key}_from"] = time.fromisoformat(filled[key]["from"])
            st.session_state[f"{prefix}_{key}_to"] = time.fromisoformat(filled[key]["to"])

    applied = apply.button("Применить Пн–Пт", on_click=apply_weekdays)
    if applied:
        st.info("График будней заполнен. Проверьте время и сохраните изменения.")
    result: dict[str, Any] = dict(schedule)
    for day_key, day_label, _ in DAYS:
        existing = schedule.get(day_key, {})
        enabled_key = f"{prefix}_{day_key}_enabled"
        enabled = st.session_state.get(enabled_key, bool(existing))
        row = st.columns([1.1, 1, 0.2, 1])
        enabled = row[0].checkbox(day_label, value=enabled, key=enabled_key)
        start = row[1].time_input(
            f"Начало {day_label}", value=time.fromisoformat(existing.get("from", "09:00")),
            key=f"{prefix}_{day_key}_from", disabled=not enabled, label_visibility="collapsed",
        )
        row[2].markdown("—")
        end = row[3].time_input(
            f"Окончание {day_label}", value=time.fromisoformat(existing.get("to", "18:00")),
            key=f"{prefix}_{day_key}_to", disabled=not enabled, label_visibility="collapsed",
        )
        if enabled:
            result[day_key] = {"from": start.strftime("%H:%M"), "to": end.strftime("%H:%M")}
        else:
            result.pop(day_key, None)
    if legacy:
        result["_legacy"] = legacy
    error = validate_weekly_schedule(result)
    return reception_type, result, error, applied


def render_reception_schedule_summary(reception_type: Any, reception_schedule: Any) -> None:
    st.caption(reception_type_label(reception_type))
    for line in format_compact_schedule(reception_schedule, reception_type).splitlines():
        st.caption(line)
