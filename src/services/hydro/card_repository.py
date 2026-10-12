"""Canonical CRM access for hydro parking/object cards.

Разделение данных зашито в модель:
  * source-owned колонки пишет только ночной загрузчик
    (`src/services/hydro_daily_sync.py`);
  * ручные правки менеджера лежат в `manual_overrides` и загрузчик их
    не читает и не пишет.

Итоговое значение поля = `manual_overrides[key]`, иначе колонка источника.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from src.services.hydro.card_fields import manual_field_keys

MANUAL_KEYS = frozenset(manual_field_keys())

_SCHEMA_CODES = {"42P01", "42703", "42883", "42501"}

LIST_KINDS = ("leak_types", "inspection_photos")


class HydroCardSchemaMissing(RuntimeError):
    """Канонические таблицы Hydro недоступны: нужна миграция, а не «нет данных»."""


def _schema_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if getattr(current, "pgcode", None) in _SCHEMA_CODES:
            return True
        text = str(current).lower()
        if "does not exist" in text or "undefined column" in text or "permission denied" in text:
            return True
        for name in ("__cause__", "__context__", "original_exception", "orig"):
            nested = getattr(current, name, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


OBJECT_COLUMNS = """
    o.id, o.cadastral_number, o.address, o.area_total, o.floors_underground,
    o.floors_total, o.parking_type, o.parking_confidence, o.lat, o.lon,
    o.management_status, o.management_type, o.source_updated_at, o.synced_at,
    o.first_seen_at, o.last_seen_at, o.source_system, o.source_object_id,
    o.access_status, o.inspection_date, o.leak_types, o.severity,
    o.inspection_notes, o.inspection_photos, o.tech_solution_type,
    o.commercial_proposal_sum, o.commercial_proposal_file_url, o.proposal_status,
    o.tz_approved_by_client, o.tz_file_url, o.tender_url, o.tender_number,
    o.tender_nmck, o.tender_end_date, o.manual_overrides
"""

_LIST_SQL = """
SELECT {columns}, mc.id AS uk_id, mc.name AS uk_name, mc.inn AS uk_inn, mc.stage AS uk_stage
FROM parking_prefunnel_objects o
LEFT JOIN mc_parking_links l ON l.parking_object_id = o.id
LEFT JOIN management_companies mc ON mc.id = l.mc_id
""".format(columns=OBJECT_COLUMNS)

COUNT_SQL = "SELECT count(*)::int AS total FROM parking_prefunnel_objects o"

ONE_SQL = _LIST_SQL.replace(
    "FROM parking_prefunnel_objects o", "FROM parking_prefunnel_objects o", 1
) + " WHERE o.id = %s LIMIT 1"


def normalize_value(key: str, value: Any) -> Any:
    """Строка из формы -> значение jsonb. Пустое -> None (снять правку)."""
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    if isinstance(value, bool):
        return value
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    if key in LIST_KINDS:
        return [part.strip() for part in text.split(",") if part.strip()]
    if key in ("commercial_proposal_sum", "tender_nmck"):
        cleaned = text.replace(" ", "").replace("\u00a0", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return text
    return text


def effective(row: Mapping[str, Any], key: str) -> tuple[Any, bool]:
    """(значение, True если это ручной ввод менеджера)."""
    overrides = row.get("manual_overrides") or {}
    if isinstance(overrides, Mapping) and key in overrides:
        value = overrides[key]
        if value not in (None, "", [], {}):
            return value, True
    return row.get(key), False


def as_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, float) and value.is_integer():
        return f"{value:,.0f}".replace(",", " ")
    return str(value)


class HydroCardRepository:
    """Read/write hydro parking cards against the canonical CRM database."""

    def __init__(self, crm_db: Any):
        self.db = crm_db
        self.schema_available = bool(crm_db)
        self.last_schema_error: str | None = None

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        if self.db is None:
            self.schema_available = False
            self.last_schema_error = "CRM БД не подключена"
            return []
        try:
            return list(self.db.execute_query(sql, tuple(params)) or [])
        except Exception as error:  # noqa: BLE001
            if _schema_error(error):
                self.schema_available = False
                self.last_schema_error = str(error)
                return []
            raise

    def total(self) -> int:
        rows = self._query(COUNT_SQL)
        return int(rows[0]["total"]) if rows else 0

    def list_objects(self, *, text: str | None = None, only_manual: bool = False,
                     limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if text:
            clauses.append("(coalesce(o.address,'') || ' ' || coalesce(o.cadastral_number,'') "
                           "|| ' ' || coalesce(mc.name,'')) ILIKE %s")
            params.append(f"%{text}%")
        if only_manual:
            clauses.append("o.manual_overrides <> '{}'::jsonb")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"{_LIST_SQL} {where} ORDER BY o.id DESC LIMIT %s OFFSET %s"
        params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
        return self._query(sql, params)

    def get_object(self, object_id: int | str) -> dict[str, Any] | None:
        rows = self._query(f"{_LIST_SQL} WHERE o.id = %s LIMIT 1", (object_id,))
        return rows[0] if rows else None

    def save_overrides(self, object_id: int | str, values: Mapping[str, Any]) -> dict[str, Any]:
        """Слить ручные правки менеджера, не трогая колонки источника."""
        patch: dict[str, Any] = {}
        removals: list[str] = []
        for key, raw in values.items():
            if key not in MANUAL_KEYS:
                continue
            value = normalize_value(key, raw)
            if value is None:
                removals.append(key)
            else:
                patch[key] = value
        sql = """
            UPDATE parking_prefunnel_objects
               SET manual_overrides = (manual_overrides || %s::jsonb) - %s::text[],
                   updated_at = now()
             WHERE id = %s
         RETURNING manual_overrides
        """
        params = (json.dumps(patch, ensure_ascii=False, default=str), removals, object_id)
        rows = self._query(sql, params)
        return rows[0]["manual_overrides"] if rows else {}

    def source_health(self) -> dict[str, Any]:
        rows = self._query(
            "SELECT source, status, last_attempt_at, last_success_at, rows_seen,"
            " rows_inserted, rows_updated, rows_unchanged, rows_invalid,"
            " safe_error_class, safe_error_message"
            " FROM crm_hydro_source_health WHERE source = 'NSPD_PARKING'"
        )
        return rows[0] if rows else {}

    def manual_count(self) -> int:
        rows = self._query("SELECT count(*)::int AS total FROM parking_prefunnel_objects"
                           " WHERE manual_overrides <> '{}'::jsonb")
        return int(rows[0]["total"]) if rows else 0