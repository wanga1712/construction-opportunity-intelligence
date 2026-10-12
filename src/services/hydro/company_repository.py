"""Canonical CRM access for the УК card: параметры приёма, контакты, встречи.

Параметры приёма (`website`, `reception_type`, `reception_schedule`, `stage`)
заполняет менеджер, ночной синк их не трогает: загрузчик обновляет только
`name`/`inn`/адрес новой компании и никогда не перезаписывает существующую.
Дополнительно ручные правки дублируются в `management_companies.manual_overrides`
(см. `src/migrations/hydro_manual_override_1.sql`).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

RECEPTION_TYPE_LABELS = {"daily": "Живая очередь", "scheduled": "По записи"}
RECEPTION_TYPES = tuple(RECEPTION_TYPE_LABELS)

STAGE_LABELS = {
    "lead": "Новый лид",
    "meeting_scheduled": "Встреча назначена",
    "meeting_held": "Встреча проведена",
    "access_granted": "Доступ получен",
    "inspected": "Обследование проведено",
    "offer_sent": "КП отправлено",
    "tz_prep": "Подготовка ТЗ",
    "bidding": "Торги",
    "in_progress": "В работе",
    "won": "Выиграно",
    "lost": "Проиграно",
}
STAGES = tuple(STAGE_LABELS)

ACTIVITY_DEFAULT_DURATION = timedelta(hours=1)

ACTIVITY_TYPE_LABELS = {
    "meeting": "Встреча",
    "call": "Звонок",
    "inspection": "Обследование",
    "follow_up": "Касание",
}
ACTIVITY_TYPES = tuple(ACTIVITY_TYPE_LABELS)
ACTIVITY_STATUS_LABELS = {"planned": "Запланировано", "completed": "Проведено", "cancelled": "Отменено"}

COMPANY_COLUMNS = ("id, name, inn, phone:skip, website, reception_type, reception_schedule,"
                   " stage, city, actual_address, legal_address, created_at, updated_at,"
                   " manual_overrides")

_SELECT = """
SELECT c.id, c.name, c.inn, c.website, c.reception_type, c.reception_schedule, c.stage,
       c.city, c.actual_address, c.legal_address, c.updated_at, c.manual_overrides,
       (SELECT count(*)::int FROM company_contacts k WHERE k.company_id = c.id) AS contacts_count,
       (SELECT count(*)::int FROM company_activities a WHERE a.company_id = c.id) AS activities_count,
       (SELECT count(*)::int FROM mc_parking_links l WHERE l.mc_id = c.id) AS objects_count,
       (SELECT count(*)::int FROM company_contacts k WHERE k.company_id = c.id AND k.is_primary) AS primary_contacts
FROM management_companies c
"""

MANUAL_KEYS = frozenset({"website", "reception_type", "reception_schedule", "stage",
                         "phone", "actual_address", "legal_address", "city"})


def _rows(db: Any, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    if db is None:
        return []
    return list(db.execute_query(sql, tuple(params)) or [])


def reception_label(value: Any) -> str:
    return RECEPTION_TYPE_LABELS.get(str(value or "daily"), "Живая очередь")


def stage_label(value: Any) -> str:
    return STAGE_LABELS.get(str(value or "lead"), str(value or "—"))


def effective_company(company: Mapping[str, Any], key: str) -> tuple[Any, bool]:
    overrides = company.get("manual_overrides") or {}
    if isinstance(overrides, Mapping) and overrides.get(key) not in (None, "", [], {}):
        return overrides[key], True
    return company.get(key), False


def schedule_text(value: Any) -> str:
    """График приёма: jsonb {"mon": "09:00-18:00", ...} -> человекочитаемо."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    parts = [f"{day}: {slot}" for day, slot in value.items() if slot]
    return "; ".join(parts)


def _split_schedule_entry(chunk):
    """«пн 09:00-18:00» / «пн=09:00-18:00» -> (день, часы).

    Разделитель «:» не используется: он съел бы время приёма «09:00-18:00».
    """
    for separator in ("=", "\u2014"):
        if separator in chunk:
            day, _, slot = chunk.partition(separator)
            if day.strip() and slot.strip():
                return day.strip(), slot.strip()
    day, _, slot = chunk.partition(" ")
    if day.strip() and slot.strip() and not any(ch.isdigit() for ch in day):
        return day.strip(), slot.strip()
    return "", chunk.strip()


def normalize_schedule(raw):
    """Свободный текст -> jsonb графика приёма."""
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        return {str(k): str(v) for k, v in raw.items() if str(v).strip()} or None
    text = str(raw).strip()
    if not text:
        return None
    result = {}
    for chunk in text.replace(chr(10), ";").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        day, slot = _split_schedule_entry(chunk)
        result[day or f"строка {len(result) + 1}"] = slot
    return result or None


class HydroCompanyRepository:
    """Read/write УК card data. Ничего не изобретает: только свои колонки."""

    def __init__(self, crm_db: Any):
        self.db = crm_db
        self.schema_available = bool(crm_db)

    def list_companies(self, *, text: str | None = None, stage: str | None = None,
                       limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if text:
            clauses.append("(coalesce(c.name,'') || ' ' || coalesce(c.inn,'') "
                           "|| ' ' || coalesce(c.actual_address,'')) ILIKE %s")
            params.append(f"%{text}%")
        if stage:
            clauses.append("c.stage = %s")
            params.append(stage)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
        return _rows(self.db, f"{_SELECT} {where} ORDER BY c.id DESC LIMIT %s OFFSET %s", params)

    def get_company(self, company_id: int | str) -> dict[str, Any] | None:
        rows = _rows(self.db, f"{_SELECT} WHERE c.id = %s LIMIT 1", (company_id,))
        return rows[0] if rows else None

    def get_by_inn(self, inn: Any) -> dict[str, Any] | None:
        """Найти УК по ИНН: карточка УК в UI живёт на контуре, а параметры — здесь."""
        text = str(inn or "").strip()
        if not text:
            return None
        rows = _rows(self.db, f"{_SELECT} WHERE c.inn = %s ORDER BY c.id LIMIT 1", (text,))
        return rows[0] if rows else None

    def ensure_company(self, *, name: str, inn: Any = None) -> int | None:
        """Создать УК, если её ещё нет в канонической таблице (idempotent по ИНН)."""
        existing = self.get_by_inn(inn)
        if existing:
            return int(existing["id"])
        clean_name = str(name or "").strip()
        if not clean_name and not str(inn or "").strip():
            return None
        name = clean_name or f"УК {inn}"
        inn_value = str(inn).strip() or None
        if inn_value:
            sql = ("INSERT INTO management_companies (name, inn)"
                   " SELECT %s, %s WHERE NOT EXISTS"
                   " (SELECT 1 FROM management_companies WHERE inn = %s) RETURNING id")
            rows = _rows(self.db, sql, (name, inn_value, inn_value))
        else:
            rows = _rows(self.db, "INSERT INTO management_companies (name) VALUES (%s)"
                                  " RETURNING id", (name,))
        if not rows:
            return self.get_by_inn(inn_value) and int(self.get_by_inn(inn_value)["id"])
        return int(rows[0]["id"])

    def save_params(self, company_id: int | str, values: Mapping[str, Any]) -> dict[str, Any]:
        """Записать параметры приёма/стадию. Пустое значение -> снять правку."""
        patch: dict[str, Any] = {}
        for key, raw in values.items():
            if key not in MANUAL_KEYS:
                continue
            if key == "reception_schedule":
                value = normalize_schedule(raw)
            elif key == "reception_type":
                value = str(raw) if str(raw) in RECEPTION_TYPES else None
            elif key == "stage":
                value = str(raw) if str(raw) in STAGES else None
            else:
                value = (str(raw).strip() or None) if raw is not None else None
            if value:
                patch[key] = value
        if not patch:
            return self.get_company(company_id) or {}
        columns = [key for key in patch if key != "reception_schedule"]
        assignments = [f"{column} = %s" for column in columns]
        params: list[Any] = [patch[column] for column in columns]
        if "reception_schedule" in patch:
            assignments.append("reception_schedule = %s::jsonb")
            params.append(json.dumps(patch["reception_schedule"], ensure_ascii=False))
        params.append(company_id)
        _rows(self.db, f"UPDATE management_companies SET {', '.join(assignments)}, updated_at = now()"
                       f" WHERE id = %s RETURNING id", params)
        return self.get_company(company_id) or {}

    def list_contacts(self, company_id: int | str) -> list[dict[str, Any]]:
        return _rows(self.db, "SELECT id, full_name, role, phone, phone_ext, email, is_primary,"
                              " comment, created_at FROM company_contacts WHERE company_id = %s"
                              " ORDER BY is_primary DESC, id", (company_id,))

    def add_contact(self, company_id: int | str, values: Mapping[str, Any]) -> int | None:
        name = str(values.get("full_name") or "").strip()
        if not name:
            return None
        is_primary = bool(values.get("is_primary"))
        if is_primary:
            # uq_contacts_company_primary: у УК ровно один основной контакт,
            # поэтому новый основной снимает флаг у прежнего.
            _rows(self.db, "UPDATE company_contacts SET is_primary = FALSE"
                           " WHERE company_id = %s AND is_primary", (company_id,))
        rows = _rows(self.db, """
            INSERT INTO company_contacts (company_id, full_name, role, phone, phone_ext, email,
                                          is_primary, comment)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (company_id, name, values.get("role") or None, values.get("phone") or None,
              values.get("phone_ext") or None, values.get("email") or None,
              is_primary, values.get("comment") or None))
        return int(rows[0]["id"]) if rows else None

    def list_activities(self, company_id: int | str) -> list[dict[str, Any]]:
        return _rows(self.db, "SELECT id, activity_type, title, description, start_time, end_time,"
                              " status, created_at FROM company_activities WHERE company_id = %s"
                              " ORDER BY start_time DESC NULLS LAST, id DESC", (company_id,))

    def add_activity(self, company_id: int | str, values: Mapping[str, Any]) -> int | None:
        kind = str(values.get("activity_type") or "meeting")
        if kind not in ACTIVITY_TYPES:
            kind = "meeting"
        start = values.get("start_time") or datetime.now().replace(microsecond=0)
        # company_activities.end_time NOT NULL: встреча по умолчанию идёт час.
        end = values.get("end_time") or (start + ACTIVITY_DEFAULT_DURATION)
        rows = _rows(self.db, """
            INSERT INTO company_activities (company_id, activity_type, title, description,
                                            start_time, end_time, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (company_id, kind, str(values.get("title") or ACTIVITY_TYPE_LABELS[kind]),
              values.get("description") or None, start, end,
              str(values.get("status") or "planned")))
        return int(rows[0]["id"]) if rows else None
