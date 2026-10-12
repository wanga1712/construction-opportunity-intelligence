"""615-ПП (капремонт) slice for the waterproofing УК CRM.

Заказчиком торгов 615-ПП выступает региональный оператор капремонта (ФКР), а не
управляющая компания, поэтому связь с УК идёт не по ИНН, а по адресам домов:
дома из портфеля УК сопоставляются с адресом поставки контракта.

Срез берётся за всю доступную историю (с 2019 года) и отвечает на вопросы
«были ли уже торги по капремонту у домов этой УК» и «какой объём торгов
разыгран в текущем году». Адрес в 615-ПП и в НСПД записан по-разному, поэтому
сопоставление идёт по номеру дома и пересечению слов названия улицы.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

from psycopg2.extras import RealDictCursor

from modules.crm.analytics.tender_row_utils import query_dicts

from src.services.waterproofing_crm import format_amount

TENDER_TABLE = "public.reestr_contract_615_pp"
HISTORY_FROM_YEAR = 2019
# Минимальное совпадение слов улицы, чтобы считать дом тем же самым.
MATCH_THRESHOLD = 0.5


class TenderSourceUnavailable(RuntimeError):
    """Источник торгов 615-ПП недоступен (связь, права, отсутствие таблицы).

    «Нет прав» и «торгов нет» — разные факты: вызывающий код обязан показать
    первый как недоступность данных, а не как ноль.
    """

    def __init__(self, reason: str, *, original: BaseException | None = None):
        self.reason = str(reason)
        self.original = original
        super().__init__(f"615-PP source unavailable: {self.reason}")

AddressKey = tuple[str, str]
StreetParts = tuple[frozenset[str], str]

# Тип улицы в адресах 615-ПП и НСПД пишут по-разному ("просп.", "пр-кт",
# "пр."), поэтому все варианты просто выбрасываются: ключ строится по
# названию улицы и номеру дома.
_STREET_TYPES: frozenset[str] = frozenset({
    "ул", "улица", "улицы", "улицу", "пр", "просп", "проспект", "проспекта",
    "проспекту", "пер", "переулок", "переулка", "проезд", "проезда", "прд",
    "бул", "бульвар", "бульв", "бульвара", "бр", "ш", "шоссе", "шосс",
    "наб", "набережная", "набережную", "пл", "площадь", "аллея", "алл",
    "туп", "тупик", "тупиковый", "квартал", "просек", "просека", "линия",
    "линии", "мкр", "микрорайон", "микрорайона", "проулок", "проулки",
})

# Маркеры района/округа: следующее за ними название к улице не относится.
_DISTRICT_MARKERS: frozenset[str] = frozenset({"округ", "район", "городской", "о"})

_HYPHEN_FIXES: tuple[tuple[str, str], ...] = (
    ("пр-кт", "проспект"), ("пр-т", "проспект"), ("пр-д", "проезд"),
    ("б-р", "бульвар"), ("кв-л", "квартал"), ("наб-я", "набережная"),
    ("р-н", "район"), ("г.о", "городской округ"), ("ш-се", "шоссе"),
)

# Сокращения, которые раскрываются, чтобы «Серпуховская Б.» и «Большая
# Серпуховская» дали один ключ.
_STREET_ABBR: dict[str, str] = {
    "б": "большая", "м": "малая", "им": "имени", "акад": "академика",
    "ген": "генерала", "марш": "маршала", "гв": "гвардии",
    "верхн": "верхняя", "нижн": "нижняя", "средн": "средняя",
    "нов": "новая", "стар": "старая", "бол": "большая", "мал": "малая",
}

_NOISE_TOKENS: frozenset[str] = frozenset({
    "российская", "федерация", "город", "г", "москва", "вн", "тер", "округ",
    "муниципальный", "область", "обл", "район", "поселок", "пгт", "село",
    "деревня", "д", "дом", "к", "корп", "корпус", "стр", "строение", "соор",
    "сооружение", "владение", "влд", "литера", "лит", "пом", "этаж",
    "пос", "рп", "с", "и", "п", "о", "снт", "массив", "уч", "городской",
})

_ORDINAL_RE = re.compile(r"\b\d+-[а-яa-z]+")
_TOKEN_RE = re.compile(r"[0-9]+[а-яa-z]*|[а-яa-z]+")


def _tokenize(value: Any) -> list[str]:
    lowered = str(value or "").lower().replace("ё", "е")
    for source, target in _HYPHEN_FIXES:
        lowered = lowered.replace(source, target)
    lowered = _ORDINAL_RE.sub(" ", lowered).replace("/", " к ")
    return _TOKEN_RE.findall(lowered)


def _address_parts(value: Any) -> StreetParts | None:
    """Слова названия улицы и номер дома; None для неполного адреса."""
    street: list[str] = []
    numbers: list[str] = []
    skip_budget = 0
    for token in _tokenize(value):
        if token in _STREET_TYPES:
            skip_budget = 0
            continue
        if token in _DISTRICT_MARKERS:
            skip_budget = 2
            continue
        if token[:1].isdigit():
            numbers.append(token)
            skip_budget = 0
            continue
        if skip_budget > 0:
            skip_budget -= 1
            continue
        if token in _NOISE_TOKENS:
            continue
        street.append(_STREET_ABBR.get(token, token))
    if not street or not numbers:
        return None
    return frozenset(street), numbers[0]


def address_key(value: Any) -> AddressKey | None:
    """Ключ сопоставления «улица + дом» для адреса 615-ПП или НСПД.

    Понимает оба формата: «Бестужевых ул. 21» и «Российская Федерация, город
    Москва, вн.тер.г. муниципальный округ Раменки, проспект Ломоносовский,
    дом 27, корпус 4». Корпус, строение и округ в ключ не входят. Возвращает
    None, если адрес не домовый (например, «Москва»).
    """
    parts = _address_parts(value)
    if parts is None:
        return None
    return (" ".join(sorted(parts[0])), parts[1])


normalize_address = address_key


def similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Пересечение слов улицы: 1.0 — полное совпадение, 0.0 — ничего общего."""
    if not left or not right:
        return 0.0
    return len(left & right) / float(len(left | right))


def _amount(row: dict[str, Any]) -> float:
    for field in ("final_price", "initial_price"):
        value = row.get(field)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _year_of(value: Any) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() else None


def contract_view(row: dict[str, Any]) -> dict[str, Any]:
    """Нормализованное представление контракта для индекса по адресам."""
    start = str(row.get("start_date") or "")
    return {
        "id": str(row.get("id") or ""),
        "number": str(row.get("contract_number") or ""),
        "date": start[:10],
        "year": _year_of(start),
        "amount": _amount(row),
        "waterproofing": bool(row.get("is_waterproofing")),
    }


def _615_sql(year: int | None) -> tuple[str, tuple[Any, ...]]:
    if year:
        clause = "r.start_date >= %s AND r.start_date < %s"
        params: tuple[Any, ...] = (date(int(year), 1, 1), date(int(year) + 1, 1, 1))
    else:
        clause = "r.start_date >= %s"
        params = (date(HISTORY_FROM_YEAR, 1, 1),)
    return (
        "SELECT r.id, r.contract_number, r.start_date, r.initial_price, r.final_price, "
        "       r.is_waterproofing, r.delivery_address, r.delivery_region, r.work_kind_name "
        f"FROM {TENDER_TABLE} r "
        f"WHERE {clause} "
        "ORDER BY r.start_date DESC",
        params,
    )


def _fetch_rows_strict(tender_db, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Строгое чтение источника: любая ошибка — исключение, а не пустой список.

    Штатный `query_dicts` глотает исключения и возвращает `[]`, из-за чего
    «нет прав на таблицу» выглядит как «торгов нет». Здесь этого не происходит.
    """
    if tender_db is None:
        raise TenderSourceUnavailable("источник торгов не подключён")
    try:
        if tender_db.is_offline_mode():
            raise TenderSourceUnavailable(
                "источник торгов в офлайн-режиме",
                original=getattr(tender_db, "get_connection_error", lambda: None)(),
            )
        if not tender_db.is_connected():
            tender_db.connect()
        conn = tender_db.get_connection()
        if conn is None:
            raise TenderSourceUnavailable("нет соединения с источником торгов")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    except TenderSourceUnavailable:
        raise
    except Exception as error:  # noqa: BLE001 — конвертируем в доменную ошибку
        raise TenderSourceUnavailable(
            f"{type(error).__name__}: {error}", original=error
        ) from error


def fetch_615_rows(
    tender_db, year: int | None = None, *, strict: bool = False
) -> list[dict[str, Any]]:
    """Контракты 615-ПП: за конкретный год либо за всю доступную историю.

    `strict=True` поднимает `TenderSourceUnavailable` вместо пустого результата.
    """
    sql, params = _615_sql(year)
    if strict:
        return _fetch_rows_strict(tender_db, sql, params)
    return query_dicts(tender_db, sql, params)


def build_index(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Индекс контрактов: номер дома -> варианты названия улицы (все годы)."""
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        parts = _address_parts(row.get("delivery_address"))
        if parts is None:
            continue
        street, number = parts
        for entry in index.setdefault(number, []):
            if entry["street"] == street:
                entry["contracts"].append(contract_view(row))
                break
        else:
            index[number].append({"street": street, "contracts": [contract_view(row)]})
    return index


def match_entry(
    index: dict[str, list[dict[str, Any]]], value: Any, *, threshold: float = MATCH_THRESHOLD
) -> tuple[dict[str, Any] | None, float]:
    """Найти дом в индексе: точное совпадение или лучшее по пересечению слов."""
    parts = _address_parts(value)
    if parts is None:
        return None, 0.0
    street, number = parts
    best: dict[str, Any] | None = None
    best_score = 0.0
    for entry in index.get(number) or []:
        score = similarity(street, entry["street"])
        if score > best_score:
            best, best_score = entry, score
    if best is not None and (best_score >= 1.0 or best_score >= threshold):
        return best, best_score
    return None, best_score


def entry_totals(entry: dict[str, Any] | None, year: int | None = None) -> dict[str, Any]:
    """Свернуть контракты одного дома: за конкретный год или за всю историю."""
    contracts = [c for c in (entry or {}).get("contracts") or [] if year is None or c.get("year") == year]
    amount = sum(float(c.get("amount") or 0.0) for c in contracts)
    waterproofing = [c for c in contracts if c.get("waterproofing")]
    return {
        "tenders": len(contracts),
        "amount": amount,
        "waterproofing_tenders": len(waterproofing),
        "waterproofing_amount": sum(float(c.get("amount") or 0.0) for c in waterproofing),
        "last_date": max((str(c.get("date") or "") for c in contracts), default=""),
        "contracts": contracts,
    }


def entry_years(entry: dict[str, Any] | None) -> list[int]:
    years = {c.get("year") for c in (entry or {}).get("contracts") or []}
    return sorted(year for year in years if year)


def year_overview(rows: Iterable[dict[str, Any]], year: int) -> dict[str, Any]:
    """Объём всей программы 615-ПП за год: сколько уже разыграно."""
    contracts = [row for row in rows if _year_of(row.get("start_date")) == int(year)]
    amount = sum(_amount(row) for row in contracts)
    waterproofing = [row for row in contracts if row.get("is_waterproofing")]
    waterproofing_amount = sum(_amount(row) for row in waterproofing)
    return {
        "year": str(year),
        "tenders": len(contracts),
        "amount": amount,
        "amount_label": format_amount(amount),
        "waterproofing_tenders": len(waterproofing),
        "waterproofing_amount": waterproofing_amount,
        "waterproofing_amount_label": format_amount(waterproofing_amount),
    }


def program_years(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Объём всей программы 615-ПП по каждому году, где есть контракты."""
    materialized = list(rows)
    years = sorted(
        {year for year in (_year_of(row.get("start_date")) for row in materialized) if year}
    )
    return [year_overview(materialized, year) for year in years]


def load_615_slice(
    tender_db, *, year: int | None = None, strict: bool = False
) -> dict[str, Any]:
    """Один проход по 615-ПП: история по адресам домов и объём текущего года.

    `strict=True` — источник обязателен: ошибка чтения поднимается наружу
    (`TenderSourceUnavailable`), а не превращается в «торгов нет».
    """
    target_year = int(year or date.today().year)
    rows = fetch_615_rows(tender_db, strict=strict)
    return {
        "year": target_year,
        "history_from": HISTORY_FROM_YEAR,
        "rows": rows,
        "overview": year_overview(rows, target_year),
        "index": build_index(rows),
    }


def empty_summary(year: Any = "") -> dict[str, Any]:
    return {
        "year": str(year or ""), "tenders": 0, "amount": 0.0, "waterproofing_tenders": 0,
        "waterproofing_amount": 0.0, "last_date": "", "matched_addresses": 0,
        "matches": [], "has_tenders": False, "amount_label": "—",
        "waterproofing_amount_label": "—", "overview": {}, "checked_addresses": 0,
        "history_tenders": 0, "history_amount": 0.0, "history_amount_label": "—",
        "history_waterproofing_tenders": 0, "history_last_date": "", "years": [],
        "history_from": HISTORY_FROM_YEAR, "approximate_matches": 0,
    }


def summarize_addresses(slice_data: dict[str, Any] | None, addresses: Iterable[Any]) -> dict[str, Any]:
    """Свернуть торги 615-ПП по домам одной УК: история и текущий год."""
    data = slice_data or {}
    index = data.get("index") or {}
    year = data.get("year") or date.today().year
    summary = empty_summary(year)
    summary["overview"] = data.get("overview") or {}
    summary["history_from"] = data.get("history_from") or HISTORY_FROM_YEAR
    seen: set[Any] = set()
    years: set[int] = set()
    for address in addresses:
        parts = _address_parts(address)
        if parts is None or parts in seen:
            continue
        seen.add(parts)
        summary["checked_addresses"] += 1
        entry, score = match_entry(index, address)
        if entry is None:
            continue
        lifetime = entry_totals(entry)
        if not lifetime["tenders"]:
            continue
        current = entry_totals(entry, year)
        years.update(entry_years(entry))
        if score < 1.0:
            summary["approximate_matches"] += 1
        summary["tenders"] += current["tenders"]
        summary["amount"] += current["amount"]
        summary["waterproofing_tenders"] += current["waterproofing_tenders"]
        summary["waterproofing_amount"] += current["waterproofing_amount"]
        summary["history_tenders"] += lifetime["tenders"]
        summary["history_amount"] += lifetime["amount"]
        summary["history_waterproofing_tenders"] += lifetime["waterproofing_tenders"]
        if current["last_date"] > summary["last_date"]:
            summary["last_date"] = current["last_date"]
        if lifetime["last_date"] > summary["history_last_date"]:
            summary["history_last_date"] = lifetime["last_date"]
        summary["matches"].append({
            "address": " ".join(str(address or "").split())[:160],
            "tenders": lifetime["tenders"],
            "amount": lifetime["amount"],
            "amount_label": format_amount(lifetime["amount"]),
            "last_date": lifetime["last_date"],
            "tenders_current_year": current["tenders"],
            "amount_current_year_label": format_amount(current["amount"]),
            "years": entry_years(entry),
            "confidence": "точное" if score >= 1.0 else f"похожий адрес {int(score * 100)}%",
            "contracts": lifetime["contracts"],
        })
    summary["matched_addresses"] = len(summary["matches"])
    summary["amount_label"] = format_amount(summary["amount"])
    summary["waterproofing_amount_label"] = format_amount(summary["waterproofing_amount"])
    summary["history_amount_label"] = format_amount(summary["history_amount"])
    summary["years"] = sorted(years)
    summary["has_tenders"] = summary["history_tenders"] > 0
    return summary


def group_addresses_by_uk(object_rows: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    """Разложить адреса объектов по ключу контура УК (ОГРН, иначе ИНН)."""
    grouped: dict[str, list[str]] = {}
    for row in object_rows:
        key = str(row.get("uk_ogrn") or row.get("uk_inn") or "").strip()
        address = row.get("address_text")
        if not key or not address:
            continue
        grouped.setdefault(key, []).append(address)
    return grouped


__all__ = [
    "HISTORY_FROM_YEAR",
    "MATCH_THRESHOLD",
    "TENDER_TABLE",
    "TenderSourceUnavailable",
    "address_key",
    "build_index",
    "contract_view",
    "empty_summary",
    "entry_totals",
    "entry_years",
    "fetch_615_rows",
    "group_addresses_by_uk",
    "load_615_slice",
    "match_entry",
    "normalize_address",
    "program_years",
    "similarity",
    "summarize_addresses",
    "year_overview",
]
