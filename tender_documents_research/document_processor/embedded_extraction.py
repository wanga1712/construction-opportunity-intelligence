"""EMBEDDED_EXTRACTION_NORMALIZATION_V1 - category-bound structured extraction.

Turns parsed text/tables of an already-selected, category-bound document into
structured commercial facts:

    material/product -> quantity -> unit -> normalized unit/family
    -> unit price / line total -> provenance

Design rules (from the WIP):
  * no model guesses - only deterministic table/line parsing;
  * category context comes from the caller (registry category_code), never a
    parallel taxonomy;
  * unit + quantity are stored raw AND normalized; normalization is family
    bounded (COUNT / AREA / LENGTH / MASS / VOLUME) - incompatible units are
    never coerced;
  * every fact carries provenance (document, page/sheet, row/line, quote);
  * identical positions dedupe by a stable fingerprint.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

EXTRACTOR_VERSION = "EMBEDDED_EXTRACTOR_V1"
NORMALIZER_VERSION = "UNIT_NORMALIZER_V1"

COUNT = "COUNT"
AREA = "AREA"
LENGTH = "LENGTH"
MASS = "MASS"
VOLUME = "VOLUME"

_NBSP = "\u00a0\u202f"
_MULTI_SPACE = re.compile(r"\s{2,}")


# ---------------------------------------------------------------- normalization

_UNIT_MAP: Dict[str, Tuple[str, str]] = {
    # count
    "шт": ("PCS", COUNT),
    "штука": ("PCS", COUNT),
    "штук": ("PCS", COUNT),
    "штуки": ("PCS", COUNT),
    "pcs": ("PCS", COUNT),
    "ед": ("UNIT", COUNT),
    "единиц": ("UNIT", COUNT),
    "единица": ("UNIT", COUNT),
    "единицы": ("UNIT", COUNT),
    "компл": ("SET", COUNT),
    "комплект": ("SET", COUNT),
    "комплектов": ("SET", COUNT),
    "набор": ("SET", COUNT),
    "set": ("SET", COUNT),
    "рулон": ("ROLL", COUNT),
    "рулонов": ("ROLL", COUNT),
    "рул": ("ROLL", COUNT),
    "упак": ("PACK", COUNT),
    "упаковка": ("PACK", COUNT),
    "упаковок": ("PACK", COUNT),
    "пачк": ("PACK", COUNT),
    "пачка": ("PACK", COUNT),
    "меш": ("BAG", COUNT),
    "мешок": ("BAG", COUNT),
    "мешков": ("BAG", COUNT),
    "лист": ("SHEET", COUNT),
    "листов": ("SHEET", COUNT),
    "пара": ("PAIR", COUNT),
    "пар": ("PAIR", COUNT),
    # length
    "м": ("M", LENGTH),
    "метр": ("M", LENGTH),
    "метров": ("M", LENGTH),
    "метра": ("M", LENGTH),
    "м.п": ("M", LENGTH),
    "мп": ("M", LENGTH),
    "пог.м": ("M", LENGTH),
    "погм": ("M", LENGTH),
    "пм": ("M", LENGTH),
    "mm": ("MM", LENGTH),
    "мм": ("MM", LENGTH),
    "см": ("CM", LENGTH),
    "cm": ("CM", LENGTH),
    "км": ("KM", LENGTH),
    "km": ("KM", LENGTH),
    # area
    "м2": ("M2", AREA),
    "м^2": ("M2", AREA),
    "кв.м": ("M2", AREA),
    "квм": ("M2", AREA),
    "квадратный метр": ("M2", AREA),
    "m2": ("M2", AREA),
    "см2": ("CM2", AREA),
    "cm2": ("CM2", AREA),
    "га": ("HA", AREA),
    # mass
    "кг": ("KG", MASS),
    "kg": ("KG", MASS),
    "г": ("G", MASS),
    "гр": ("G", MASS),
    "gram": ("G", MASS),
    "т": ("T", MASS),
    "тн": ("T", MASS),
    "тонна": ("T", MASS),
    "тонн": ("T", MASS),
    "ton": ("T", MASS),
    # volume
    "л": ("L", VOLUME),
    "литр": ("L", VOLUME),
    "литров": ("L", VOLUME),
    "l": ("L", VOLUME),
    "м3": ("M3", VOLUME),
    "м^3": ("M3", VOLUME),
    "куб.м": ("M3", VOLUME),
    "кубм": ("M3", VOLUME),
    "m3": ("M3", VOLUME),
}

_HEADER_TOKENS = (
    "наименование",
    "наим.",
    "ед. изм",
    "ед изм",
    "единица измерения",
    "кол-во",
    "количество",
    "цена",
    "стоимость",
    "сумма",
    "итого",
    "всего",
    "в том числе",
    "№",
    "п/п",
    "поз.",
    "артикул",
    "показатель",
    "номер",
)

#: Summary/aggregate rows that are never commercial line positions.
_AGGREGATE_NAME = (
    "цена контракта",
    "твердая цена",
    "твёрдая цена",
    "ндс",
    "итого",
    "всего",
    "итог ",
    "общая стоимость",
    "общий итог",
    "сумма по",
    "стартовая цена",
    "начальная (максимальная) цена",
    "оср",
    "ведомость объемов",
    "локальн",
)


def _is_aggregate_name(name: str) -> bool:
    low = (name or "").strip().lower()
    return any(tok in low for tok in _AGGREGATE_NAME)

_MATERIAL_HINTS = (
    "материал",
    "товар",
    "продукц",
    "издели",
    "оборудован",
    "покрыт",
    "плитк",
    "линолеум",
    "кабел",
    "труб",
    "светильник",
    "мастик",
    "мембран",
    "арматур",
    "бордюр",
    "композит",
    "бетон",
    "раствор",
    "смесь",
    "краск",
    "грунт",
    "праймер",
    "профиль",
    "панель",
    "настил",
    "ограждени",
    "опор",
)

_BAD_NAME = re.compile(
    r"(^\s*\d)"                        # rows starting with a number/position
    r"|(ул\.|д\.\s*\d|район|обл\.|объект по адресу)"  # addresses
    r"|(октмо|инн|кпп|бик|огрн|лицевой счет)"          # codes
    r"|(дата|время|срок|окончани|beginn|подач[аи] заявок)"
    r"|(разъяснени|участник|порядок|в течение|в соответств)"
    r"|(итого|всего|ндс|приложени|раздел)"
    r"|(единица измерения|наименование|кол-во|количество|цена|стоимость|сумма)",
    re.IGNORECASE,
)


def _canon_unit_key(raw: str) -> str:
    s = (raw or "").strip().lower()
    s = s.replace("ё", "е").replace("\u00b2", "2").replace("\u00b3", "3")
    for ch in _NBSP:
        s = s.replace(ch, " ")
    s = re.sub(r"\s+", " ", s).strip(" .,;:")
    return s


def normalize_unit(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(unit_normalized, measurement_family) or (None, None)."""
    if not raw:
        return None, None
    key = _canon_unit_key(raw)
    if key in _UNIT_MAP:
        return _UNIT_MAP[key]
    key2 = key.replace(" ", "")
    if key2 in _UNIT_MAP:
        return _UNIT_MAP[key2]
    return None, None


def parse_number(raw: Optional[str]) -> Optional[float]:
    """Russian/space thousands + comma decimals -> float; None if not a number."""
    if raw is None:
        return None
    s = str(raw)
    for ch in _NBSP:
        s = s.replace(ch, "")
    s = s.replace(" ", "")
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s or s in {"-", ".", ","}:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def split_quantity_unit(cell: Optional[str]) -> Optional[Tuple[float, str, Optional[str], Optional[str]]]:
    """Parse a cell that carries a quantity and (optionally) a unit.

    Examples: "1 250,5 м2", "200 Метр", "50 м", "1 компл", "30м".
    Returns (quantity, unit_raw, unit_normalized, family) or None.
    """
    if not cell:
        return None
    s = str(cell)
    for ch in _NBSP:
        s = s.replace(ch, " ")
    s = re.sub(r"\s+", " ", s).strip()
    m = re.match(r"^([\-+]?\d[\d\s.,]*)\s*([^\d].*)?$", s)
    if not m:
        return None
    value = parse_number(m.group(1))
    if value is None:
        return None
    unit_raw = (m.group(2) or "").strip(" .,;:|") or None
    unit_norm, family = normalize_unit(unit_raw)
    # A trailing unit cell may itself be a bare number column value; only accept
    # the unit when it is short and not another number.
    if unit_raw and len(unit_raw) > 20:
        # A long "tail" is not a unit token (e.g. "1 комплект ... по ТЗ").
        unit_raw, unit_norm, family = None, None, None
    if unit_raw and parse_number(unit_raw) is not None and unit_norm is None:
        return None
    return value, unit_raw, unit_norm, family


# ---------------------------------------------------------------------- facts


@dataclass
class ExtractedFact:
    procurement_id: int
    category_code: str
    document_name: str
    product_name_raw: str
    source_quote: str
    source_document_id: Optional[int] = None
    physical_download_key: Optional[str] = None
    page_or_sheet: Optional[str] = None
    row_or_line: Optional[str] = None
    product_name_normalized: Optional[str] = None
    quantity_raw: Optional[str] = None
    quantity_value: Optional[float] = None
    unit_raw: Optional[str] = None
    unit_normalized: Optional[str] = None
    measurement_family: Optional[str] = None
    unit_price_raw: Optional[str] = None
    unit_price_value: Optional[float] = None
    line_total_raw: Optional[str] = None
    line_total_value: Optional[float] = None
    confidence: float = 0.0
    category_match: bool = False
    entity_fingerprint: str = ""
    extractor_version: str = EXTRACTOR_VERSION
    normalizer_version: str = NORMALIZER_VERSION
    layout_status: Optional[str] = None


def normalize_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).replace("ё", "е").replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:400] or None


def fingerprint(fact: ExtractedFact, row_key: str) -> str:
    material = (fact.product_name_normalized or fact.product_name_raw or "").lower()
    payload = "|".join(
        [
            str(fact.procurement_id),
            str(fact.source_document_id or fact.document_name),
            str(fact.page_or_sheet or ""),
            row_key,
            material,
            str(fact.quantity_value if fact.quantity_value is not None else ""),
            str(fact.unit_normalized or fact.unit_raw or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_header(cell: str) -> bool:
    low = cell.strip().lower()
    if not low:
        return True
    return any(tok in low for tok in _HEADER_TOKENS) and len(low) < 40


_COL_MARKERS = {
    "name": ("наименован", "характеристик", "параметр", "показател", "товар", "материал", "позици"),
    "unit": ("единиц", "ед. изм", "ед.изм", "ед "),
    "qty": ("кол-во", "количество", "кол."),
    "price": ("цена",),
    "total": ("стоимост", "сумма", "итого"),
}


def _header_mapping(cells: Sequence[str]) -> Dict[str, int]:
    """Detect a table header row and map semantic columns to indices."""
    low = [str(c).strip().lower() for c in cells]
    mapping: Dict[str, int] = {}
    for key, markers in _COL_MARKERS.items():
        for i, cell in enumerate(low):
            if any(m in cell for m in markers) and i not in mapping.values():
                mapping[key] = i
                break
    # a real header must expose at least quantity or price/total plus a name
    if "name" in mapping and ("qty" in mapping or "price" in mapping or "total" in mapping):
        return mapping
    return {}


def _split_row_cells(row_text: str, meta: Dict[str, Any]) -> List[str]:
    cells = meta.get("cells") if isinstance(meta, dict) else None
    if cells:
        out = [str(c.get("text", "")).strip() for c in cells if str(c.get("text", "")).strip()]
        if out:
            return out
    if "|" in row_text:
        return [p.strip() for p in row_text.split("|") if p.strip()]
    return [p.strip() for p in _MULTI_SPACE.split(row_text) if p.strip()]


def _iter_rows(text: str, line_meta: Optional[Dict[int, Any]]) -> Iterable[Tuple[int, str, Dict[str, Any]]]:
    meta = line_meta or {}
    for line_no, line in enumerate((text or "").splitlines(), start=1):
        row_text = line.strip()
        if not row_text:
            continue
        row_meta = meta.get(line_no) or {}
        # Only table rows are evidence: plain prose lines produce dates/addresses.
        is_table = bool(row_meta.get("cells")) or " | " in row_text
        if is_table:
            yield line_no, row_text, row_meta


def _row_to_fact(
    *,
    procurement_id: int,
    category_code: str,
    document_name: str,
    source_document_id: Optional[int],
    physical_key: Optional[str],
    line_no: int,
    row_text: str,
    meta: Dict[str, Any],
    category_keywords: Sequence[str],
    header_map: Optional[Dict[str, int]] = None,
) -> Optional[ExtractedFact]:
    cells = _split_row_cells(row_text, meta)
    if not cells:
        return None

    layout_status = None
    mapped_qty = mapped_unit = mapped_price = mapped_total = None
    if header_map:
        def _val(key: str) -> Optional[str]:
            idx = header_map.get(key)
            return cells[idx].strip() if idx is not None and 0 <= idx < len(cells) else None

        mapped_qty_cell = _val("qty")
        if mapped_qty_cell:
            parsed = split_quantity_unit(mapped_qty_cell)
            mapped_qty = parsed[0] if parsed else parse_number(mapped_qty_cell)
        mapped_unit = _val("unit")
        mapped_price = parse_number(_val("price")) if _val("price") else None
        mapped_total = parse_number(_val("total")) if _val("total") else None
        if mapped_qty is not None and mapped_unit is None and mapped_qty_cell:
            parsed = split_quantity_unit(mapped_qty_cell)
            if parsed and parsed[1]:
                mapped_unit = parsed[1]
        # reconciliation
        if mapped_qty is not None and mapped_price is not None and mapped_total is not None:
            computed = float(mapped_qty) * float(mapped_price)
            denom = max(abs(float(mapped_total)), abs(computed), 1.0)
            if abs(float(mapped_total) - computed) / denom > 0.05:
                layout_status = "INCONSISTENT_LAYOUT"
                mapped_total = None
            else:
                layout_status = "CONSISTENT"
        elif mapped_price is not None:
            layout_status = "CONSISTENT"
        else:
            # A total without a price column cannot be verified against a
            # position (aggregate/contract sums live here) -> no value.
            layout_status = "UNSUPPORTED_LAYOUT"
            mapped_total = None

    # name = best material-looking cell (net of address/date/enumeration noise)
    low_row = row_text.lower()
    best_name = ""
    best_score = -1
    for cell in cells:
        if _is_header(cell):
            continue
        alpha = sum(1 for ch in cell if ch.isalpha())
        if alpha < 3 or len(cell) > 140:
            continue
        words = len(cell.split())
        if words > 12:
            continue
        score = alpha
        if any(h in cell.lower() for h in _MATERIAL_HINTS):
            score += 60
        if any(kw and kw in cell.lower() for kw in category_keywords):
            score += 40
        if _BAD_NAME.search(cell):
            score -= 200
        if score > best_score:
            best_score = score
            best_name = cell
    name = best_name
    if not name or best_score < 0:
        return None
    if _is_aggregate_name(name):
        return None

    # quantity + unit: combined cell first, then bare-unit + bare-number pairing
    qty = unit_raw = unit_norm = family = None
    used_idx: set = set()
    for idx, cell in enumerate(cells):
        if cell is name:
            continue
        parsed = split_quantity_unit(cell)
        if parsed and parsed[2]:
            qty, unit_raw, unit_norm, family = parsed
            used_idx.add(idx)
            break
    if qty is None:
        unit_idx = number_idx = None
        for idx, cell in enumerate(cells):
            if cell is name:
                continue
            un, _fam = normalize_unit(cell)
            is_unit = bool(un) and len(_canon_unit_key(cell)) <= 12
            if is_unit:
                unit_idx = idx if unit_idx is None else unit_idx
            elif number_idx is None and not is_unit and parse_number(cell) is not None:
                number_idx = idx
        if number_idx is not None:
            qty = parse_number(cells[number_idx])
            used_idx.add(number_idx)
            if unit_idx is not None:
                unit_raw = cells[unit_idx]
                unit_norm, family = normalize_unit(unit_raw)
                used_idx.add(unit_idx)
    if qty is None:
        parsed = split_quantity_unit(row_text)
        if parsed:
            qty, unit_raw, unit_norm, family = parsed

    # money cells: remaining numeric cells
    money: List[Tuple[int, float, str]] = []
    for idx, cell in enumerate(cells):
        if idx in used_idx or cell is name:
            continue
        val = parse_number(cell)
        if val is None:
            continue
        money.append((idx, val, cell))
    unit_price_value = unit_price_raw = line_total_value = line_total_raw = None
    if header_map:
        unit_price_value = mapped_price
        unit_price_raw = str(mapped_price) if mapped_price is not None else None
        line_total_value = mapped_total
        line_total_raw = str(mapped_total) if mapped_total is not None else None
        qty = mapped_qty
        unit_raw = mapped_unit
        unit_norm, family = normalize_unit(unit_raw)
        # A category VALUE is only trusted on a real position: quantity + unit.
        if qty is None or unit_norm is None:
            unit_price_value = unit_price_raw = None
            line_total_value = line_total_raw = None
            layout_status = "UNSUPPORTED_LAYOUT"
    else:
        # No recognisable header: material/quantity may be kept, but a value is
        # NEVER guessed from neighbouring numbers.
        layout_status = "UNSUPPORTED_LAYOUT"

    # An evidence fact requires a unit-bound quantity (no unit -> not a fact).
    if qty is None or unit_norm is None:
        return None

    low = row_text.lower()
    category_match = any(kw and kw in low for kw in category_keywords)
    material_hint = any(h in name.lower() for h in _MATERIAL_HINTS)

    confidence = 0.4
    if qty is not None and unit_norm:
        confidence = 0.9
    elif qty is not None:
        confidence = 0.75
    elif line_total_value is not None:
        confidence = 0.6
    if category_match:
        confidence = min(0.98, confidence + 0.05)
    elif material_hint:
        confidence = min(0.95, confidence + 0.03)

    fact = ExtractedFact(
        procurement_id=procurement_id,
        category_code=category_code,
        document_name=document_name,
        source_document_id=source_document_id,
        physical_download_key=physical_key,
        page_or_sheet=(
            str(meta.get("sheet_name"))
            if meta.get("sheet_name")
            else (str(meta.get("page_number")) if meta.get("page_number") else None)
        ),
        row_or_line=(
            f"row{meta.get('row_index')}"
            if meta.get("row_index")
            else f"line{line_no}"
        ),
        product_name_raw=name,
        product_name_normalized=normalize_name(name),
        quantity_raw=(str(qty) if qty is not None else None),
        quantity_value=qty,
        unit_raw=unit_raw,
        unit_normalized=unit_norm,
        measurement_family=family,
        unit_price_raw=unit_price_raw,
        unit_price_value=unit_price_value,
        line_total_raw=line_total_raw,
        line_total_value=line_total_value,
        source_quote=row_text[:500],
        confidence=confidence,
        category_match=category_match,
        layout_status=layout_status,
    )
    row_key = str(fact.row_or_line)
    fact.entity_fingerprint = fingerprint(fact, row_key)
    return fact


def extract_facts(
    *,
    procurement_id: int,
    category_code: str,
    document_name: str,
    text: Optional[str],
    line_meta: Optional[Dict[int, Any]] = None,
    source_document_id: Optional[int] = None,
    physical_key: Optional[str] = None,
    category_keywords: Sequence[str] = (),
    require_quantity: bool = False,
) -> List[ExtractedFact]:
    """Deterministic row-level extraction for one category-bound document."""
    facts: List[ExtractedFact] = []
    seen: set = set()
    max_rows = int(os.getenv("EMBEDDED_MAX_ROWS", "200000"))
    processed = 0
    # Header-aware column mapping per table: qty/price/total only from their own
    # columns; a headerless table yields material/quantity but NO value.
    headers: Dict[Any, Dict[str, int]] = {}
    for line_no, row_text, meta in _iter_rows(text or "", line_meta):
        processed += 1
        if processed > max_rows:
            break
        cells = _split_row_cells(row_text, meta)
        table_key = (meta.get("table_index"), meta.get("sheet_name"), meta.get("file", ""))
        mapping = _header_mapping(cells)
        if mapping:
            headers[table_key] = mapping
            continue
        fact = _row_to_fact(
            procurement_id=procurement_id,
            category_code=category_code,
            document_name=document_name,
            source_document_id=source_document_id,
            physical_key=physical_key,
            line_no=line_no,
            row_text=row_text,
            meta=meta,
            category_keywords=category_keywords,
            header_map=headers.get(table_key),
        )
        if fact is None:
            continue
        if require_quantity and fact.quantity_value is None:
            continue
        if fact.entity_fingerprint in seen:
            continue
        seen.add(fact.entity_fingerprint)
        facts.append(fact)
    return facts


def facts_from_table_rows(
    *,
    procurement_id: int,
    category_code: str,
    document_name: str,
    rows: Iterable[Any],
    source_document_id: Optional[int] = None,
    physical_key: Optional[str] = None,
    category_keywords: Sequence[str] = (),
) -> List[ExtractedFact]:
    """Adapt pre-read table facts (xlsx reader) to the same normalized contract."""
    out: List[ExtractedFact] = []
    seen: set = set()
    for r in rows or []:
        name = getattr(r, "product_name_raw", None)
        if not name:
            continue
        if _is_aggregate_name(str(name)):
            continue
        unit_raw = getattr(r, "quantity_unit", None)
        unit_norm, family = normalize_unit(unit_raw)
        qty = getattr(r, "quantity_value", None)
        up = getattr(r, "unit_price_value", None)
        tot = getattr(r, "total_price_value", None)
        # A value requires a real position: quantity + unit (+ price column).
        if qty is None or unit_norm is None or (up is None and tot is not None):
            up = None
            tot = None
        layout_status = "CONSISTENT"
        if qty is not None and up is not None and tot is not None:
            computed = float(qty) * float(up)
            denom = max(abs(float(tot)), abs(computed), 1.0)
            if abs(float(tot) - computed) / denom > 0.05:
                layout_status = "INCONSISTENT_LAYOUT"
                tot = None
        elif up is None and tot is not None:
            # unverifiable total (no price column) -> not a usable value
            layout_status = "UNSUPPORTED_LAYOUT"
            tot = None
        quote = getattr(r, "source_quote", "") or ""
        fact = ExtractedFact(
            procurement_id=procurement_id,
            category_code=category_code,
            document_name=document_name,
            source_document_id=source_document_id,
            physical_download_key=physical_key,
            page_or_sheet=None,
            row_or_line=(f"row{getattr(r, 'row', '')}" if getattr(r, "row", None) else None),
            product_name_raw=name,
            product_name_normalized=normalize_name(name),
            quantity_raw=(str(qty) if qty is not None else None),
            quantity_value=(float(qty) if qty is not None else None),
            unit_raw=unit_raw,
            unit_normalized=unit_norm,
            measurement_family=family,
            unit_price_raw=(str(up) if up is not None else None),
            unit_price_value=(float(up) if up is not None else None),
            line_total_raw=(str(tot) if tot is not None else None),
            line_total_value=(float(tot) if tot is not None else None),
            source_quote=quote[:500],
            confidence=0.9 if (qty is not None and unit_norm) else 0.7,
            category_match=any(kw and kw in quote.lower() for kw in category_keywords),
            layout_status=layout_status,
        )
        fact.entity_fingerprint = fingerprint(fact, str(fact.row_or_line or ""))
        if fact.entity_fingerprint in seen:
            continue
        seen.add(fact.entity_fingerprint)
        out.append(fact)
    return out
