"""Ежедневная загрузка канонического среза Hydro в CRM БД.

Паттерн тот же, что у связки 615-ПП (`src/services/waterproofing_615_refresh.py`):

    nspd_parking (READ ONLY)                 — объекты-паркинги и УК
      → src.services.hydro.source_repository — канонический контракт источника
      → src.services.hydro.persistence_repository — upsert по
        source_system+source_object_id / кадастру / ИНН УК
      → CRM БД (parking_prefunnel_objects, management_companies, crm_hydro_*)

Правило разделения данных: загрузчик пишет ТОЛЬКО колонки источника. Ручные
правки менеджера лежат в `manual_overrides` и по построению не читаются и не
перезаписываются (см. `src/migrations/hydro_manual_override_1.sql`).

Ошибка загрузки не затирает последний успех: `last_success_at` сохраняется,
статус становится FAILED, текст ошибки виден в мониторинге.

Никакого DDL: схему создают миграции `src/migrations/hydro_*.sql`.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from src.services.hydro.persistence_repository import HydroPersistenceRepository
from src.services.hydro.source_repository import NspdSourceRepository

SOURCE = "NSPD_PARKING"
MAX_ERROR_MESSAGE = 400

_HEALTH_SUCCESS = """
INSERT INTO crm_hydro_source_health
 (source, status, last_attempt_at, last_success_at, rows_seen, rows_inserted,
  rows_updated, rows_unchanged, rows_invalid, safe_error_class, safe_error_message)
VALUES (%(source)s, 'SUCCESS', %(attempt)s, %(attempt)s, %(rows_seen)s, %(rows_inserted)s,
        %(rows_updated)s, %(rows_unchanged)s, %(rows_invalid)s, NULL, NULL)
ON CONFLICT (source) DO UPDATE SET
 status = 'SUCCESS', last_attempt_at = EXCLUDED.last_attempt_at,
 last_success_at = EXCLUDED.last_success_at, rows_seen = EXCLUDED.rows_seen,
 rows_inserted = EXCLUDED.rows_inserted, rows_updated = EXCLUDED.rows_updated,
 rows_unchanged = EXCLUDED.rows_unchanged, rows_invalid = EXCLUDED.rows_invalid,
 safe_error_class = NULL, safe_error_message = NULL
"""

# Провал не должен затирать last_success_at: UI показывает последние успешные
# данные и честно сообщает, что свежих нет.
_HEALTH_FAILURE = """
INSERT INTO crm_hydro_source_health
 (source, status, last_attempt_at, safe_error_class, safe_error_message)
VALUES (%(source)s, 'FAILED', %(attempt)s, %(error_class)s, %(error_message)s)
ON CONFLICT (source) DO UPDATE SET
 status = 'FAILED', last_attempt_at = EXCLUDED.last_attempt_at,
 safe_error_class = EXCLUDED.safe_error_class,
 safe_error_message = EXCLUDED.safe_error_message
"""

HEALTH_SELECT = """
SELECT source, status, last_attempt_at, last_success_at, rows_seen, rows_inserted,
       rows_updated, rows_unchanged, rows_invalid, safe_error_class, safe_error_message
FROM crm_hydro_source_health WHERE source = 'NSPD_PARKING'
"""


class HydroSyncUnavailable(RuntimeError):
    """Канонические таблицы Hydro не готовы или CRM БД недоступна."""


def connection_of(db: Any) -> Any:
    """Живое соединение CRM. Тот же контракт, что у 615-ПП refresh."""
    if db is None:
        raise HydroSyncUnavailable("Hydro: CRM БД не подключена")
    if hasattr(db, "get_connection"):
        conn = db.get_connection()
    else:
        ensure = getattr(db, "_ensure_connection", None)
        if callable(ensure):
            ensure()
        conn = getattr(db, "_connection", None)
    if conn is None:
        raise HydroSyncUnavailable(f"Hydro: нет соединения с CRM БД ({db.__class__.__name__})")
    return conn


def ensure_tables(crm_db: Any) -> None:
    """Fail-closed: без канонических таблиц не пишем и не показываем «ноль»."""
    required = ("parking_prefunnel_objects", "management_companies")
    missing: list[str] = []
    for table in required:
        rows = crm_db.execute_query("SELECT to_regclass(%s) AS oid", (f"public.{table}",))
        if not rows or rows[0]["oid"] is None:
            missing.append(table)
    if missing:
        raise HydroSyncUnavailable("Hydro: нет таблиц " + ", ".join(missing))


def read_health(crm_db: Any) -> dict[str, Any]:
    if crm_db is None:
        return {}
    try:
        rows = crm_db.execute_query(HEALTH_SELECT) or []
    except Exception:  # noqa: BLE001 — мониторинг не должен падать из-за статуса
        return {}
    return rows[0] if rows else {}


def write_health_success(conn: Any, counts: dict[str, Any], *, attempt: datetime) -> None:
    state = {
        "source": SOURCE, "attempt": attempt,
        "rows_seen": int(counts.get("source_rows_total", 0) or 0),
        "rows_inserted": int(counts.get("prefunnel_rows_inserted", 0) or 0),
        "rows_updated": int(counts.get("prefunnel_rows_updated", 0) or 0),
        "rows_unchanged": int(counts.get("prefunnel_rows_unchanged", 0) or 0),
        "rows_invalid": int(counts.get("invalid_rows", 0) or 0),
    }
    with conn.cursor() as cur:
        cur.execute(_HEALTH_SUCCESS, state)
    conn.commit()


def write_health_failure(conn: Any, error: BaseException, *, attempt: datetime) -> None:
    state = {
        "source": SOURCE, "attempt": attempt,
        "error_class": type(error).__name__,
        "error_message": str(error)[:MAX_ERROR_MESSAGE],
    }
    try:
        with conn.cursor() as cur:
            cur.execute(_HEALTH_FAILURE, state)
        conn.commit()
    except Exception:  # noqa: BLE001 — провал телеметрии не должен скрывать исходную ошибку
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass


def _record_failure(crm_db: Any, error: BaseException, attempt: datetime) -> None:
    try:
        write_health_failure(connection_of(crm_db), error, attempt=attempt)
    except Exception:  # noqa: BLE001 — исходная ошибка важнее записи о ней
        pass


def run_daily_sync(
    *, source_db: Any = None, crm_db: Any = None, dry_run: bool = False,
    limit: int | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Полный цикл: источник → канонический upsert → статус в CRM.

    Возвращает отчёт (для systemd-логов, мониторинга и тестов).
    """
    started = time.monotonic()
    attempt = now or datetime.now(timezone.utc)
    if source_db is None:
        from src.services.parking_db import ParkingDatabase

        source_db = ParkingDatabase()
        source_db.connect()
    if crm_db is None:
        raise HydroSyncUnavailable("Hydro: CRM БД не подключена")
    try:
        objects = NspdSourceRepository(source_db).fetch_objects()
        if limit:
            objects = objects[: int(limit)]
        repo = HydroPersistenceRepository(connection_of(crm_db))
        counts = repo.sync(objects, dry_run=bool(dry_run))
    except Exception as error:  # noqa: BLE001 — любой сбой источника/записи = FAILED
        _record_failure(crm_db, error, attempt)
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    report: dict[str, Any] = {
        "status": "DRY_RUN" if dry_run else "SUCCESS",
        "source": SOURCE,
        "rows_loaded": int(counts.get("source_rows_total", 0) or 0),
        "lead_eligible": int(counts.get("lead_eligible_rows", 0) or 0),
        "inserted": int(counts.get("prefunnel_rows_inserted", 0) or 0),
        "updated": int(counts.get("prefunnel_rows_updated", 0) or 0),
        "unchanged": int(counts.get("prefunnel_rows_unchanged", 0) or 0),
        "invalid": int(counts.get("invalid_rows", 0) or 0),
        "companies_created": int(counts.get("management_companies_created", 0) or 0),
        "duration_ms": duration_ms,
        "attempt_at": attempt.isoformat(),
    }
    return report