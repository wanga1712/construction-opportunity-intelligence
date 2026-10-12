"""CRM-side store for the 615-ПП ↔ УК linkage (read side).

Связка «дома УК → торги капремонта 615-ПП» считается один раз в сутки
(`scripts/refresh_waterproofing_615_link.py`) и лежит в CRM БД. Доска не
обращается к источнику и не выполняет нечёткое сопоставление на каждый
rerun: она читает готовые агрегаты одним запросом.

Никакого DDL: таблицы создаются миграцией
`src/migrations/waterproofing_615_uk_link_store_1.sql`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.services.schema_guard import SchemaNotReady, require_relations_or_raise
from src.services.waterproofing_615 import HISTORY_FROM_YEAR
from src.services.waterproofing_crm import format_amount

SYNC_SOURCE = "TENDER_MONITOR_615"
STALE_AFTER_HOURS = 36

STORE_TABLES = (
    "crm_waterproofing_615_program_year",
    "crm_waterproofing_615_uk_address",
    "crm_waterproofing_615_uk_link",
    "crm_waterproofing_615_sync_state",
)

STATUS_FRESH = "fresh"
STATUS_STALE = "stale"
STATUS_FAILED = "failed"
STATUS_NEVER_RUN = "never_run"
STATUS_UNAVAILABLE = "unavailable"

UNAVAILABLE_TEXT = "615-ПП недоступны: хранилище CRM не создано"


class StoreUnavailable(RuntimeError):
    """CRM-хранилище связки 615-ПП не готово или не подключено."""


class StoreNotReady(StoreUnavailable):
    """Таблиц связки нет в CRM БД: нужна миграция, а не «ноль торгов»."""

    def __init__(self, missing: list[str]):
        self.missing = list(missing)
        super().__init__(f"{UNAVAILABLE_TEXT} ({', '.join(self.missing)})")


def ensure_store_ready(db: Any) -> None:
    """Fail-closed: таблицы связки должны существовать. DDL здесь нет."""
    if db is None:
        raise StoreUnavailable(UNAVAILABLE_TEXT)
    try:
        require_relations_or_raise(db, STORE_TABLES)
    except SchemaNotReady as error:
        raise StoreNotReady(list(error.missing)) from error
    except Exception as error:  # noqa: BLE001 — SchemaNotReady | ошибка запроса
        raise StoreUnavailable(f"615-ПП недоступны: {error}") from error


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


def _years(value: Any) -> list[int]:
    return sorted({int(year) for year in (value or []) if year})


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def empty_summary(year: Any = "") -> dict[str, Any]:
    """Сводка УК без найденных торгов — та же форма, что у `summarize_addresses`."""
    zero = format_amount(0.0)
    return {
        "year": str(year or ""), "tenders": 0, "amount": 0.0, "amount_label": zero,
        "waterproofing_tenders": 0, "waterproofing_amount": 0.0,
        "waterproofing_amount_label": zero, "last_date": "", "matched_addresses": 0,
        "matches": [], "has_tenders": False, "checked_addresses": 0, "history_tenders": 0,
        "history_amount": 0.0, "history_amount_label": zero,
        "history_waterproofing_tenders": 0, "history_last_date": "", "years": [],
        "history_from": HISTORY_FROM_YEAR, "approximate_matches": 0, "overview": {},
    }


def board_query(year: int, *, uk_key: str | None = None) -> str:
    """Один агрегирующий запрос: 615-ПП по каждой УК за историю и за год."""
    uk_filter = "WHERE uk_key = %(uk_key)s" if uk_key else ""
    return f"""
    SELECT
        a.uk_key,
        COALESCE(h.tenders, 0)            AS history_tenders,
        COALESCE(h.amount, 0)             AS history_amount,
        COALESCE(h.wp_tenders, 0)         AS history_waterproofing_tenders,
        COALESCE(h.years, ARRAY[]::int[]) AS years,
        h.last_date                       AS history_last_date,
        COALESCE(y.tenders, 0)            AS year_tenders,
        COALESCE(y.amount, 0)             AS year_amount,
        COALESCE(y.wp_tenders, 0)         AS year_waterproofing_tenders,
        COALESCE(y.wp_amount, 0)          AS year_waterproofing_amount,
        y.last_date                       AS year_last_date,
        COALESCE(m.matched_addresses, 0)  AS matched_addresses,
        COALESCE(m.approximate, 0)        AS approximate_matches,
        a.checked_addresses               AS checked_addresses
    FROM (
        SELECT uk_key, COUNT(*) AS checked_addresses
        FROM crm_waterproofing_615_uk_address {uk_filter} GROUP BY uk_key
    ) a
    LEFT JOIN (
        SELECT uk_key, COUNT(*) AS tenders, SUM(amount) AS amount,
               COUNT(*) FILTER (WHERE is_waterproofing) AS wp_tenders,
               array_agg(DISTINCT contract_year)
                   FILTER (WHERE contract_year IS NOT NULL) AS years,
               MAX(contract_date) AS last_date
        FROM crm_waterproofing_615_uk_link GROUP BY uk_key
    ) h ON h.uk_key = a.uk_key
    LEFT JOIN (
        SELECT uk_key, COUNT(*) AS tenders, SUM(amount) AS amount,
               COUNT(*) FILTER (WHERE is_waterproofing) AS wp_tenders,
               SUM(amount) FILTER (WHERE is_waterproofing) AS wp_amount,
               MAX(contract_date) AS last_date
        FROM crm_waterproofing_615_uk_link WHERE contract_year = {int(year)}
        GROUP BY uk_key
    ) y ON y.uk_key = a.uk_key
    LEFT JOIN (
        SELECT uk_key, COUNT(DISTINCT address_key) AS matched_addresses,
               COUNT(DISTINCT address_key) FILTER (WHERE match_method <> 'exact') AS approximate
        FROM crm_waterproofing_615_uk_link GROUP BY uk_key
    ) m ON m.uk_key = a.uk_key
    """


def matches_query(year: int) -> str:
    """Строки детальной карточки: найденные дома УК и объём торгов по ним."""
    return f"""
    SELECT address_key,
           MIN(address_text) AS address_text,
           COUNT(*)          AS tenders,
           SUM(amount)       AS amount,
           MAX(contract_date) AS last_date,
           array_agg(DISTINCT contract_year)
               FILTER (WHERE contract_year IS NOT NULL) AS years,
           MIN(match_score)  AS match_score,
           COUNT(*) FILTER (WHERE contract_year = {int(year)}) AS year_tenders,
           COALESCE(SUM(amount) FILTER (WHERE contract_year = {int(year)}), 0) AS year_amount
    FROM crm_waterproofing_615_uk_link
    WHERE uk_key = %(uk_key)s
    GROUP BY address_key
    ORDER BY SUM(amount) DESC, address_key
    """


def _summary_from_row(row: dict[str, Any], year: int, overview: dict[str, Any],
                      history_from: int) -> dict[str, Any]:
    summary = empty_summary(year)
    summary.update({
        "overview": overview,
        "history_from": history_from,
        "checked_addresses": _to_int(row.get("checked_addresses")),
        "history_tenders": _to_int(row.get("history_tenders")),
        "history_amount": _to_float(row.get("history_amount")),
        "history_waterproofing_tenders": _to_int(row.get("history_waterproofing_tenders")),
        "history_last_date": _iso(row.get("history_last_date")),
        "years": _years(row.get("years")),
        "matched_addresses": _to_int(row.get("matched_addresses")),
        "approximate_matches": _to_int(row.get("approximate_matches")),
        "tenders": _to_int(row.get("year_tenders")),
        "amount": _to_float(row.get("year_amount")),
        "waterproofing_tenders": _to_int(row.get("year_waterproofing_tenders")),
        "waterproofing_amount": _to_float(row.get("year_waterproofing_amount")),
        "last_date": _iso(row.get("year_last_date")),
    })
    summary["amount_label"] = format_amount(summary["amount"])
    summary["waterproofing_amount_label"] = format_amount(summary["waterproofing_amount"])
    summary["history_amount_label"] = format_amount(summary["history_amount"])
    summary["has_tenders"] = summary["history_tenders"] > 0
    return summary


def _rows(db: Any, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = db.execute_query(sql, params or {})
    return [dict(row) for row in rows or []]


def read_state(db: Any) -> dict[str, Any]:
    rows = _rows(
        db,
        "SELECT * FROM crm_waterproofing_615_sync_state WHERE source = %(source)s",
        {"source": SYNC_SOURCE},
    )
    return rows[0] if rows else {}


def read_program_year(db: Any, year: int) -> dict[str, Any]:
    """Объём всей программы 615-ПП за год. Пустой dict, если года ещё нет."""
    rows = _rows(
        db,
        "SELECT year, tenders, amount, waterproofing_tenders, waterproofing_amount, "
        "       refreshed_at FROM crm_waterproofing_615_program_year WHERE year = %(year)s",
        {"year": int(year)},
    )
    if not rows:
        return {}
    row = rows[0]
    amount = _to_float(row.get("amount"))
    waterproofing_amount = _to_float(row.get("waterproofing_amount"))
    return {
        "year": str(_to_int(row.get("year"))),
        "tenders": _to_int(row.get("tenders")),
        "amount": amount,
        "amount_label": format_amount(amount),
        "waterproofing_tenders": _to_int(row.get("waterproofing_tenders")),
        "waterproofing_amount": waterproofing_amount,
        "waterproofing_amount_label": format_amount(waterproofing_amount),
        "refreshed_at": row.get("refreshed_at"),
    }


def read_uk_matches(db: Any, uk_key: str, year: int) -> list[dict[str, Any]]:
    rows = _rows(db, matches_query(year), {"uk_key": str(uk_key)})
    matches: list[dict[str, Any]] = []
    for row in rows:
        amount = _to_float(row.get("amount"))
        year_amount = _to_float(row.get("year_amount"))
        score = _to_float(row.get("match_score"))
        tenders = _to_int(row.get("tenders"))
        matches.append({
            "address": " ".join(str(row.get("address_text") or "").split())[:160],
            "tenders": tenders,
            "amount": amount,
            "amount_label": format_amount(amount),
            "last_date": _iso(row.get("last_date")),
            "tenders_current_year": _to_int(row.get("year_tenders")),
            "amount_current_year_label": format_amount(year_amount),
            "years": _years(row.get("years")),
            "confidence": "точное" if score >= 1.0 else f"похожий адрес {int(score * 100)}%",
            "contracts": tenders,
        })
    return matches


def freshness(state: dict[str, Any], now: datetime | None = None) -> tuple[str, str]:
    """(статус, честное сообщение) по последней попытке обновления связки."""
    moment = now or datetime.now(timezone.utc)
    last_success = _aware(state.get("last_success_at"))
    status = str(state.get("status") or "")
    if status == "FAILED":
        reason = str(state.get("safe_error_class") or "ошибка источника")
        suffix = f", последние данные от {_iso(last_success)}" if last_success else ""
        return STATUS_FAILED, f"615-ПП: обновление связки не удалось ({reason}){suffix}"
    if last_success is None:
        return STATUS_NEVER_RUN, "615-ПП: связка ещё ни разу не обновлялась"
    age = moment - last_success
    if age > timedelta(hours=STALE_AFTER_HOURS):
        hours = int(age.total_seconds() // 3600)
        return STATUS_STALE, (
            f"615-ПП: данные устарели — обновление {last_success:%Y-%m-%d %H:%M} "
            f"({hours} ч назад)"
        )
    return STATUS_FRESH, ""


def read_board(db: Any, *, year: int | None = None,
               now: datetime | None = None) -> dict[str, Any]:
    """Готовый срез 615-ПП для доски: сводки по всем УК + объём программы."""
    target_year = int(year or date.today().year)
    snapshot: dict[str, Any] = {
        "available": False, "status": STATUS_UNAVAILABLE, "year": target_year,
        "state": {}, "overview": {}, "uk": {}, "message": UNAVAILABLE_TEXT,
    }
    try:
        ensure_store_ready(db)
    except StoreUnavailable as error:
        snapshot["message"] = str(error)
        return snapshot
    state = read_state(db)
    overview = read_program_year(db, target_year)
    history_from = _to_int(state.get("history_from_year")) or HISTORY_FROM_YEAR
    snapshot.update({
        "available": True,
        "state": state,
        "overview": overview,
        "uk": {
            str(row.get("uk_key")): _summary_from_row(row, target_year, overview, history_from)
            for row in _rows(db, board_query(target_year))
            if str(row.get("uk_key") or "").strip()
        },
    })
    snapshot["status"], snapshot["message"] = freshness(state, now)
    return snapshot


def read_uk_summary(db: Any, uk_key: str, *, year: int | None = None) -> dict[str, Any]:
    """Сводка 615-ПП по одной УК для детальной карточки (с найденными домами)."""
    target_year = int(year or date.today().year)
    key = str(uk_key or "").strip()
    if not key:
        return {}
    try:
        ensure_store_ready(db)
    except StoreUnavailable:
        return {}
    rows = _rows(db, board_query(target_year, uk_key=key), {"uk_key": key})
    if not rows:
        return {}
    state = read_state(db)
    history_from = _to_int(state.get("history_from_year")) or HISTORY_FROM_YEAR
    summary = _summary_from_row(rows[0], target_year, read_program_year(db, target_year),
                                history_from)
    summary["matches"] = read_uk_matches(db, key, target_year)
    return summary


def board_615_line(snapshot: dict[str, Any], kpis: dict[str, Any]) -> dict[str, str]:
    """Честная строка 615-ПП для доски: недоступность никогда не показывается нулём."""
    status = str(snapshot.get("status") or STATUS_UNAVAILABLE)
    if status == STATUS_UNAVAILABLE:
        return {"level": "warning", "text": str(snapshot.get("message") or UNAVAILABLE_TEXT)}
    year = snapshot.get("year")
    overview = snapshot.get("overview") or {}
    if overview:
        head = (
            f"615-ПП: в {overview.get('year')} разыграно {overview.get('tenders')} торгов на "
            f"{overview.get('amount_label')}, из них гидроизоляция — "
            f"{overview.get('waterproofing_tenders')} на "
            f"{overview.get('waterproofing_amount_label')}. "
        )
    else:
        head = f"615-ПП: за {year} данных о программе капремонта нет. "
    body = (
        f"По адресам домов УК на доске торги найдены у {kpis.get('tenders_615_uk', 0)} УК: "
        f"{kpis.get('tenders_615', 0)} торгов на {kpis.get('tenders_615_amount_label')}, "
        f"в том числе в {year} — {kpis.get('tenders_615_year', 0)} "
        f"на {kpis.get('tenders_615_year_amount_label')}. "
        f"История по адресам домов с {HISTORY_FROM_YEAR} года."
    )
    refreshed = _iso((snapshot.get("state") or {}).get("last_success_at"))
    tail = f" Обновлено {refreshed}." if refreshed else ""
    level = "warning" if status in (STATUS_STALE, STATUS_FAILED, STATUS_NEVER_RUN) else "caption"
    text = head + body + tail
    if status in (STATUS_STALE, STATUS_FAILED, STATUS_NEVER_RUN):
        text = f"{snapshot.get('message')}. {text}"
    return {"level": level, "text": text}
