"""Refresh job for the 615-ПП ↔ УК linkage store in the CRM database.

Заказчиком торгов 615-ПП всегда выступает ФКР, поэтому связка с УК возможна
только по адресам домов. Эта работа выполняется один раз в сутки:

    S7 tender_monitor (READ ONLY, strict)
      + nspd_parking (портфель УК)
      → сопоставление (src.services.waterproofing_615)
      → CRM DB (crm_waterproofing_615_*)

Идемпотентность: таблицы-накопители перезаписываются целиком в одной
транзакции, поэтому повторный запуск даёт ровно то же состояние.

Никакого DDL: таблицы создаются миграцией
`src/migrations/waterproofing_615_uk_link_store_1.sql`.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

from src.services import waterproofing_615 as w615
from src.services.waterproofing_615_store import (
    SYNC_SOURCE,
    StoreUnavailable,
    ensure_store_ready,
)

ADDRESS_INSERT = (
    "INSERT INTO crm_waterproofing_615_uk_address "
    "(uk_key, address_key, address_text, match_method, match_score, contracts_count) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)
LINK_INSERT = (
    "INSERT INTO crm_waterproofing_615_uk_link "
    "(uk_key, address_key, address_text, contract_id, contract_number, contract_date, "
    " contract_year, amount, is_waterproofing, match_method, match_score) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
PROGRAM_INSERT = (
    "INSERT INTO crm_waterproofing_615_program_year "
    "(year, tenders, amount, waterproofing_tenders, waterproofing_amount) "
    "VALUES (%s, %s, %s, %s, %s)"
)

_TRUNCATE = (
    "DELETE FROM crm_waterproofing_615_uk_link",
    "DELETE FROM crm_waterproofing_615_uk_address",
    "DELETE FROM crm_waterproofing_615_program_year",
)

_STATE_SUCCESS = """
INSERT INTO crm_waterproofing_615_sync_state
 (source, status, last_attempt_at, last_success_at, duration_ms, source_contracts,
  history_from_year, checked_addresses, link_rows, uk_with_tenders,
  safe_error_class, safe_error_message)
VALUES (%(source)s, 'SUCCESS', %(attempt)s, %(attempt)s, %(duration_ms)s, %(source_contracts)s,
        %(history_from_year)s, %(checked_addresses)s, %(link_rows)s, %(uk_with_tenders)s,
        NULL, NULL)
ON CONFLICT (source) DO UPDATE SET
 status = 'SUCCESS', last_attempt_at = EXCLUDED.last_attempt_at,
 last_success_at = EXCLUDED.last_success_at, duration_ms = EXCLUDED.duration_ms,
 source_contracts = EXCLUDED.source_contracts, history_from_year = EXCLUDED.history_from_year,
 checked_addresses = EXCLUDED.checked_addresses, link_rows = EXCLUDED.link_rows,
 uk_with_tenders = EXCLUDED.uk_with_tenders,
 safe_error_class = NULL, safe_error_message = NULL
"""

# Провал обновления не должен затирать last_success_at: доска показывает
# последние успешные данные и честно сообщает, что свежих нет.
_STATE_FAILURE = """
INSERT INTO crm_waterproofing_615_sync_state
 (source, status, last_attempt_at, duration_ms, safe_error_class, safe_error_message)
VALUES (%(source)s, 'FAILED', %(attempt)s, %(duration_ms)s, %(error_class)s, %(error_message)s)
ON CONFLICT (source) DO UPDATE SET
 status = 'FAILED', last_attempt_at = EXCLUDED.last_attempt_at,
 duration_ms = EXCLUDED.duration_ms,
 safe_error_class = EXCLUDED.safe_error_class,
 safe_error_message = EXCLUDED.safe_error_message
"""

MAX_ERROR_MESSAGE = 400


def _connection(db: Any) -> Any:
    """Живое соединение CRM для транзакционной замены хранилища.

    Тот же контракт, что у `expert_annotation_service._transaction_connection`:
    pool-адаптеры отдают соединение через `get_connection`, боевой
    `CrmDatabaseManager` — singleton с `_ensure_connection`/`_connection`.
    Fail-closed: без соединения обновление не имеет смысла.
    """
    if db is None:
        raise StoreUnavailable("615-ПП: CRM БД не подключена")
    if hasattr(db, "get_connection"):
        conn = db.get_connection()
    else:
        ensure = getattr(db, "_ensure_connection", None)
        if callable(ensure):
            ensure()
        conn = getattr(db, "_connection", None)
    if conn is None:
        raise StoreUnavailable(f"615-ПП: нет соединения с CRM БД ({db.__class__.__name__})")
    return conn


def _flat_key(address: Any) -> str:
    parts = w615.address_key(address)
    return f"{parts[0]} {parts[1]}" if parts else ""


def build_payload(
    slice_data: Mapping[str, Any], grouped_addresses: Mapping[str, Iterable[Any]]
) -> dict[str, Any]:
    """Построить строки хранилища. Чистая функция — без БД и UI."""
    index = slice_data.get("index") or {}
    address_rows: list[tuple[Any, ...]] = []
    link_rows: list[tuple[Any, ...]] = []
    uk_with_tenders = 0
    for uk_key, addresses in grouped_addresses.items():
        seen: set[str] = set()
        matched_here = 0
        for address in addresses:
            flat = _flat_key(address)
            if not flat or flat in seen:
                continue
            seen.add(flat)
            entry, score = w615.match_entry(index, address)
            contracts = list((entry or {}).get("contracts") or [])
            method = "none"
            if contracts:
                method = "exact" if score >= 1.0 else "fuzzy"
                matched_here += 1
            text = " ".join(str(address or "").split())[:300]
            score_value = float(score)
            address_rows.append(
                (uk_key, flat, text, method, score_value, len(contracts))
            )
            for contract in contracts:
                link_rows.append((
                    uk_key, flat, text, str(contract.get("id") or ""),
                    str(contract.get("number") or ""), contract.get("date") or None,
                    contract.get("year"), float(contract.get("amount") or 0.0),
                    bool(contract.get("waterproofing")), method, score_value,
                ))
        if matched_here:
            uk_with_tenders += 1
    program_rows = [
        (int(overview["year"]), int(overview["tenders"]), float(overview["amount"]),
         int(overview["waterproofing_tenders"]), float(overview["waterproofing_amount"]))
        for overview in w615.program_years(slice_data.get("rows") or [])
    ]
    return {
        "addresses": address_rows,
        "links": link_rows,
        "program": program_rows,
        "uk_with_tenders": uk_with_tenders,
        "source_contracts": len(slice_data.get("rows") or []),
    }


def write_payload(
    conn: Any, payload: Mapping[str, Any], *, history_from: int, duration_ms: int,
    attempt: datetime | None = None,
) -> dict[str, Any]:
    """Заменить хранилище одним транзакционным проходом."""
    moment = attempt or datetime.now(timezone.utc)
    counts = {
        "addresses": len(payload["addresses"]),
        "links": len(payload["links"]),
        "program_years": len(payload["program"]),
        "uk_with_tenders": int(payload["uk_with_tenders"]),
    }
    state = {
        "source": SYNC_SOURCE, "attempt": moment, "duration_ms": int(duration_ms),
        "source_contracts": int(payload["source_contracts"]),
        "history_from_year": int(history_from),
        "checked_addresses": counts["addresses"], "link_rows": counts["links"],
        "uk_with_tenders": counts["uk_with_tenders"],
    }
    try:
        with conn.cursor() as cur:
            for sql in _TRUNCATE:
                cur.execute(sql)
            if payload["addresses"]:
                cur.executemany(ADDRESS_INSERT, payload["addresses"])
            if payload["links"]:
                cur.executemany(LINK_INSERT, payload["links"])
            if payload["program"]:
                cur.executemany(PROGRAM_INSERT, payload["program"])
            cur.execute(_STATE_SUCCESS, state)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return counts


def write_failure(
    conn: Any, error: BaseException, *, duration_ms: int, attempt: datetime | None = None
) -> None:
    """Зафиксировать провал обновления, сохранив последний успех."""
    state = {
        "source": SYNC_SOURCE,
        "attempt": attempt or datetime.now(timezone.utc),
        "duration_ms": int(duration_ms),
        "error_class": type(error).__name__,
        "error_message": str(error)[:MAX_ERROR_MESSAGE],
    }
    try:
        with conn.cursor() as cur:
            cur.execute(_STATE_FAILURE, state)
        conn.commit()
    except Exception:  # noqa: BLE001 — провал записи не должен скрывать исходную ошибку
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass


def _record_failure(crm_db: Any, error: BaseException, started: float,
                    moment: datetime) -> None:
    """Записать провал обновления, не подменяя исходную ошибку ошибкой телеметрии."""
    duration_ms = int((time.monotonic() - started) * 1000)
    try:
        write_failure(_connection(crm_db), error, duration_ms=duration_ms, attempt=moment)
    except Exception:  # noqa: BLE001 — исходная ошибка важнее записи о ней
        pass


def run_refresh(
    *, tender_db: Any = None, crm_db: Any = None, parking_db: Any = None,
    year: int | None = None, dry_run: bool = False, now: datetime | None = None,
) -> dict[str, Any]:
    """Полный цикл обновления. Возвращает отчёт (для логов и тестов)."""
    started = time.monotonic()
    moment = now or datetime.now(timezone.utc)
    if parking_db is None:
        from src.services.parking_db import ParkingDatabase

        parking_db = ParkingDatabase()
    from src.services.map_export import fetch_uk_object_addresses

    ensure_store_ready(crm_db)
    try:
        # Любой недоступный источник — это провал обновления, а не «нет торгов».
        grouped = w615.group_addresses_by_uk(fetch_uk_object_addresses(parking_db))
        slice_data = w615.load_615_slice(tender_db, year=year, strict=True)
    except Exception as error:  # noqa: BLE001
        _record_failure(crm_db, error, started, moment)
        raise
    payload = build_payload(slice_data, grouped)
    duration_ms = int((time.monotonic() - started) * 1000)
    report: dict[str, Any] = {
        "status": "DRY_RUN" if dry_run else "SUCCESS",
        "target_year": int(year or date.today().year),
        "source_contracts": payload["source_contracts"],
        "addresses": len(payload["addresses"]),
        "links": len(payload["links"]),
        "program_years": len(payload["program"]),
        "uk_with_tenders": payload["uk_with_tenders"],
        "duration_ms": duration_ms,
    }
    if not dry_run:
        written = write_payload(
            _connection(crm_db), payload, history_from=w615.HISTORY_FROM_YEAR,
            duration_ms=duration_ms, attempt=moment,
        )
        report.update(written)
    return report
