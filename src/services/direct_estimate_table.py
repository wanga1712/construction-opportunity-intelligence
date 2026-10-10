"""Реконструкция сметной таблицы прямой поставки из извлечённых строк документов.

Первичные таблицы имеют многоуровневые шапки (объединённые ячейки, переносы слов),
поэтому назначение столбца определяется по всем строкам шапки, а не по одной.
Каждое значение имеет провенанс: документ / вычислено / ориентировочно из НМЦК.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_MONTHS = None  # не используется, оставлено для совместимости стиля


def _squash(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _num(value: Any) -> Optional[float]:
    text = _norm(value).replace("\u00a0", " ")
    text = re.sub(r"[^\d,.\-]", "", text.replace(" ", ""))
    if not text:
        return None
    text = text.replace(",", ".")
    if text.count(".") > 1:
        head, _, tail = text.rpartition(".")
        text = head.replace(".", "") + "." + tail
    try:
        return float(text)
    except ValueError:
        return None


COLUMN_MARKERS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("number", ("№п/п", "№", "п/п", "номерпозиции")),
    ("name", ("наименование", "товар", "описаниеобъекта")),
    ("okpd", ("окпд", "кодпродукции", "кодтовара")),
    ("registry", ("реестр", "рэп", "российскойрадиоэлектронной")),
    ("qty", ("кол-во", "количество", "объем", "объём")),
    ("unit", ("единица", "ед.изм", "едизм")),
    ("price", ("цена", "стоимостьединицы", "ценазаединицу")),
    ("sum", ("сумма", "стоимость", "всего")),
)
_ITEM_KEY_MARKERS = ("характеристик", "значени", "параметр")


def _column_titles(rows: List[List[str]], header_index: int) -> List[str]:
    """Собрать название колонки из всех строк шапки (учитывая многоуровневость)."""
    header = rows[header_index] if header_index < len(rows) else []
    parts_above: List[List[str]] = []
    for row in rows[:header_index]:
        parts_above.append([_norm(c) for c in row])
    titles: List[str] = []
    for col, cell in enumerate(header):
        chunks: List[str] = []
        for row in parts_above:
            value = _norm(row[col]) if col < len(row) else ""
            if value and (not chunks or chunks[-1] != value):
                chunks.append(value)
        value = _norm(cell)
        if value and (not chunks or chunks[-1] != value):
            chunks.append(value)
        titles.append(" | ".join(chunks))
    return titles


def _map_columns(titles: List[str]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    squashed = [_squash(t) for t in titles]
    for key, markers in COLUMN_MARKERS:
        if key in mapping:
            continue
        for idx, title in enumerate(squashed):
            if key == "name" and any(marker in title for marker in _ITEM_KEY_MARKERS) \
                    and "товар" not in title and "наименование" not in title.replace("характеристик", ""):
                continue
            if key == "sum" and "сумманалога" in title:
                continue
            if any(_squash(marker) in title for marker in markers):
                if key == "number" and "номер" in title and "позиц" not in title:
                    continue
                mapping[key] = idx
                break
    return mapping


def _cell(cells: List[str], idx: Optional[int]) -> str:
    if idx is None or idx < 0 or idx >= len(cells):
        return ""
    return _norm(cells[idx])


def build_estimate(extraction: Dict[str, Any], nmck: Optional[float] = None) -> Dict[str, Any]:
    """Вернуть позиции сметы, итоги и объяснение по неиспользованным колонкам."""
    rows_out: List[Dict[str, Any]] = []
    not_shown: List[str] = []
    skipped_notes: List[str] = []
    document_total: Optional[float] = None
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in extraction.get("spec") or []:
        key = (str(row.get("source_file")), " | ".join(_norm(h) for h in (row.get("header") or [])))
        groups.setdefault(key, []).append(row)

    index = 0
    for (source_file, _header_sig), items in groups.items():
        header = [_norm(h) for h in (items[0].get("header") or [])]
        titles = _column_titles([header], 0)
        mapping = _map_columns(titles)
        header_squash = _squash(" ".join(titles))
        # Таблицы обоснования НМЦК — не состав закупки, а расчёт цены.
        if "коммерческоепредложение" in header_squash or "обоснованиенмцк" in header_squash \
                or "обоснованиеначальной" in header_squash:
            skipped_notes.append("%s: таблица обоснования НМЦК (%d строк) — не смета"
                                 % (source_file, len(items)))
            continue
        known = set(mapping.values())
        for idx, title in enumerate(titles):
            if idx not in known and title:
                not_shown.append("%s: %s" % (source_file, title))
        for item in items:
            cells = [_norm(c) for c in (item.get("cells") or [])]
            joined = _squash(" ".join(cells))
            name = _cell(cells, mapping.get("name"))
            if not name or not re.search(r"[A-Za-zА-Яа-я]", name):
                continue
            # Повторная строка шапки внутри данных (перенос многоуровневой шапки).
            marker_hits = sum(1 for _key, markers in COLUMN_MARKERS
                              if any(_squash(m) in _squash(" ".join(cells)) for m in markers))
            if marker_hits >= 2 and not _num(_cell(cells, mapping.get("qty"))):
                skipped_notes.append("%s: строка шапки внутри данных «%s»" % (source_file, name[:60]))
                continue
            if any(marker in joined for marker in ("итого", "всего", "нмцк", "начальнаямаксимальная")):
                total_value = _num(_cell(cells, mapping.get("sum"))) or _num(_cell(cells, mapping.get("price")))
                if total_value and total_value > 0:
                    document_total = total_value
                continue
            if re.search(r"начальная|максимальная", name, re.I) and re.search(r"цена|контракт", name, re.I):
                skipped_notes.append("%s: строка НМЦК «%s»" % (source_file, name[:60]))
                continue
            index += 1
            qty = _num(_cell(cells, mapping.get("qty")))
            unit = _cell(cells, mapping.get("unit"))
            price = _num(_cell(cells, mapping.get("price")))
            total = _num(_cell(cells, mapping.get("sum")))
            price_source = "document" if price else None
            if not price and total and qty:
                price = round(total / qty, 4)
                price_source = "computed"
            if total and qty and not _cell(cells, mapping.get("price")):
                total_source = "document"
            elif total:
                total_source = "document"
            elif price and qty:
                total = round(price * qty, 2)
                total_source = "computed"
            else:
                total_source = None
            rows_out.append({
                "index": index,
                "name": name,
                "okpd": _cell(cells, mapping.get("okpd")) or None,
                "registry": _cell(cells, mapping.get("registry")) or None,
                "qty": qty,
                "unit": unit or None,
                "unit_price": price,
                "unit_price_source": price_source,
                "sum": total,
                "sum_source": total_source,
                "source_file": source_file,
            })

    units = {row["unit"] for row in rows_out if row.get("unit")}
    with_sum = [row for row in rows_out if row.get("sum")]
    total_sum = round(sum(row["sum"] for row in with_sum), 2) if with_sum else None
    nmck_share = None
    if nmck and rows_out and not any(row.get("unit_price") for row in rows_out):
        quantity = sum(row["qty"] for row in rows_out if row.get("qty"))
        if quantity:
            nmck_share = round(float(nmck) / quantity, 2)
            for row in rows_out:
                if row.get("qty"):
                    row["unit_price"] = nmck_share
                    row["unit_price_source"] = "nmck_share"
    totals = {
        "positions": len(rows_out),
        "positions_with_sum": len(with_sum),
        "total_sum": total_sum,
        "document_total": document_total,
        "total_units": round(sum(r["qty"] for r in rows_out if r.get("qty")), 4)
        if rows_out and len(units) <= 1 else None,
        "unit": next(iter(units)) if len(units) == 1 else None,
        "nmck": nmck,
        "nmck_diff": (round(total_sum - float(nmck), 2)
                      if total_sum is not None and nmck and len(with_sum) == len(rows_out) else None),
        "complete": bool(rows_out) and len(with_sum) == len(rows_out),
    }
    return {"rows": rows_out, "totals": totals,
            "columns_not_shown": sorted(set(not_shown)),
            "skipped": sorted(set(skipped_notes))}
