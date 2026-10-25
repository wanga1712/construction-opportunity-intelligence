"""DIRECT track extraction bridge.

Routing rule (PARSE_TIME_EXTRACTION_WIRING_V2):
  * DIRECT (прямые поставки) -> previously built template extractor
    `src/services/direct_document_extractor.py` (L1 templates: spec/tech/requirements,
    delivery terms). Loaded by path so the worker venv does not import the CRM package.
  * EMBEDDED (проекты/объекты) -> embedded_extraction (EMBEDDED_EXTRACTOR_V1).

The DIRECT extractor returns structured rows; we rebuild them into table lines and
reuse the same normalizer + persistence contract, so both tracks land in the same
`structured_entities` shape (category-bound, unit-normalized, with provenance).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .embedded_extraction import normalize_unit, parse_number, split_quantity_unit
from .estimate_value_mapping import (
    find_arithmetic_triple,
    quantity_for_unit,
    select_arithmetic_pair,
)
from .direct_template_registry import resolve_direct_template_for_path

logger = logging.getLogger("direct_runtime")

DIRECT_EXTRACTOR_PATH = os.getenv(
    "DIRECT_EXTRACTOR_PATH", "/opt/CRM_Streamlit/src/services/direct_document_extractor.py"
)

_MODULE = None


def _load_module():
    global _MODULE
    if _MODULE is not None:
        return _MODULE
    path = Path(DIRECT_EXTRACTOR_PATH)
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("crm_direct_document_extractor", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE = module
    return module


def build_direct_text(path: Path) -> str:
    """Run the DIRECT template extractor and flatten its rows to table lines."""
    module = _load_module()
    if module is None:
        return ""
    lines: List[str] = []
    try:
        tables = module.extract_tables([str(path)]) or {}
    except Exception:
        tables = {}
    for kind in ("spec", "tech", "requirements"):
        for row in tables.get(kind, []) or []:
            cells = [str(c).strip() for c in (row.get("cells") or []) if str(c).strip()]
            if cells:
                lines.append(" | ".join(cells))
    try:
        terms = module.extract_delivery_terms([str(path)]) or {}
    except Exception:
        terms = {}
    for key in ("delivery_period_raw", "delivery_place_raw", "source_quote"):
        value = terms.get(key) if isinstance(terms, dict) else None
        if value:
            lines.append(f"СРОК ПОСТАВКИ | {value}")
    return "\n".join(lines)


def direct_facts(
    path: Path,
    *,
    procurement_id: int,
    category_code: str,
    document_name: str,
    source_document_id: Optional[int],
    physical_key: Optional[str],
    text: Optional[str] = None,
    line_meta: Optional[Dict[int, Any]] = None,
    document_class: Optional[str] = None,
) -> List[Any]:
    """DIRECT facts via strict category/track/class/format template."""
    from document_processor.embedded_extraction import (
        ExtractedFact,
        extract_facts,
        fingerprint,
        normalize_name,
        normalize_unit,
        parse_number,
        split_quantity_unit,
    )

    template = resolve_direct_template_for_path(
        path,
        category_code=category_code,
        opportunity_track="DIRECT_SUPPLY",
        document_class=document_class,
    )
    if template is None:
        logger.info(
            "DIRECT template not found: category=%s class=%s format=%s doc=%s",
            category_code, document_class, path.suffix.lower(), document_name,
        )
        return []

    module = _load_module()
    facts: List[ExtractedFact] = []
    seen: set = set()
    if module is not None:
        try:
            tables = module.extract_tables([str(path)]) or {}
        except Exception:
            tables = {}
        for kind in template.accepted_kinds:
            for row in tables.get(kind, []) or []:
                cells = [str(c).strip() for c in (row.get("cells") or [])]
                header = [str(h).strip().lower() for h in (row.get("header") or [])]
                if not any(cells):
                    continue
                name_indexes = _find_all(
                    header, "наименован", "характеристик", "параметр",
                    "показател", "товар",
                )
                name = row.get("item") or (
                    _cell(cells, name_indexes[0]) if name_indexes else ""
                )
                if not name:
                    name = max(
                        (c for c in cells if sum(ch.isalpha() for ch in c) >= 3),
                        key=len,
                        default="",
                    )
                if not name or sum(ch.isalpha() for ch in name) < 3:
                    continue

                qty_indexes = _find_all(
                    header, "кол-во", "количество", "кол.", "объем", "объём"
                )
                unit_indexes = _find_all(
                    header, "единиц", "ед. изм", "ед.изм", "ед "
                )
                price_indexes = _find_all(header, "цена")
                total_indexes = _find_all(
                    header, "стоимост", "сумма", "итого", "всего", "затрат"
                )

                raw_qty = None
                qty_index = None
                unit_raw = None
                for idx in qty_indexes:
                    value = _cell(cells, idx)
                    parsed = split_quantity_unit(value)
                    if parsed:
                        raw_qty = parsed[0]
                        unit_raw = parsed[1]
                        qty_index = idx
                        break
                    parsed_qty = parse_number(value)
                    if parsed_qty is not None:
                        raw_qty = parsed_qty
                        qty_index = idx
                        break

                if unit_raw is None:
                    for idx in unit_indexes:
                        value = _cell(cells, idx)
                        if value and normalize_unit(value)[0]:
                            unit_raw = value
                            break
                if unit_raw is None and qty_index is not None:
                    unit_raw = _nearest_unit(
                        cells, qty_index, name_indexes + price_indexes + total_indexes
                    )
                if raw_qty is None or unit_raw is None:
                    trailing_qty, trailing_unit = _trailing_qty_unit(cells)
                    if raw_qty is None:
                        raw_qty = trailing_qty
                    if unit_raw is None:
                        unit_raw = trailing_unit

                unit_norm, family = normalize_unit(unit_raw)
                qty = quantity_for_unit(raw_qty, unit_norm)
                prices = []
                for idx in price_indexes:
                    value = parse_number(_cell(cells, idx))
                    if value is not None:
                        prices.append((idx, value))
                totals = []
                for idx in total_indexes:
                    value = parse_number(_cell(cells, idx))
                    if value is not None:
                        totals.append((idx, value))
                pair = select_arithmetic_pair(qty, prices, totals)
                if pair is None:
                    numeric = _numeric_candidates(
                        cells,
                        header,
                        excluded=set(name_indexes + unit_indexes),
                    )
                    triple = find_arithmetic_triple(numeric)
                    if triple is not None:
                        _qidx, raw_qty, _pidx, unit_price, _tidx, line_total, _ = triple
                        qty = quantity_for_unit(raw_qty, unit_norm)
                        pair = (_pidx, unit_price, _tidx, line_total, 0.0)

                unit_price = line_total = None
                if pair is not None:
                    _price_idx, unit_price, _total_idx, line_total, _ = pair
                    layout_status = "CONSISTENT"
                elif qty is not None and prices and totals:
                    layout_status = "INCONSISTENT_LAYOUT"
                else:
                    layout_status = "UNSUPPORTED_LAYOUT"

                if qty is None or not unit_norm:
                    continue
                quote = " | ".join(cells)[:500]
                if "составляет" in quote.lower() or "рублей" in quote.lower() and " | " not in quote:
                    continue
                fact = ExtractedFact(
                    procurement_id=procurement_id,
                    category_code=category_code,
                    document_name=document_name,
                    source_document_id=source_document_id,
                    physical_download_key=physical_key,
                    row_or_line=f"drow{len(facts) + 1}",
                    product_name_raw=name,
                    product_name_normalized=normalize_name(name),
                    quantity_raw=(str(qty) if qty is not None else None),
                    quantity_value=qty,
                    unit_raw=unit_raw,
                    unit_normalized=unit_norm,
                    measurement_family=family,
                    unit_price_raw=(str(unit_price) if unit_price is not None else None),
                    unit_price_value=unit_price,
                    line_total_raw=(str(line_total) if line_total is not None else None),
                    line_total_value=line_total,
                    source_quote=quote,
                    confidence=0.9 if (qty is not None and unit_norm) else 0.7,
                    category_match=True,
                    layout_status=layout_status,
                )
                fact.entity_fingerprint = fingerprint(fact, str(fact.row_or_line))
                if fact.entity_fingerprint in seen:
                    continue
                seen.add(fact.entity_fingerprint)
                facts.append(fact)

    return facts


def _normalized_quote(value: Any) -> str:
    parts = []
    for part in str(value or "").split("|"):
        text = part.strip()
        if len(text) > 2 and text[1] == "=" and text[0].isupper():
            text = text[2:].strip()
        if text:
            parts.append(re.sub(r"\s+", " ", text))
    return "|".join(parts)


def _fact_score(fact: Any) -> tuple:
    """Prefer DIRECT fields when the same source row also came from fallback."""
    return (
        4 if getattr(fact, "layout_status", None) == "CONSISTENT" else 1,
        int(fact.line_total_value is not None),
        int(fact.unit_price_value is not None),
        int(fact.quantity_value is not None),
        int(bool(fact.unit_normalized)),
    )


def _merge_fact_sets(primary: List[Any], fallback: List[Any]) -> List[Any]:
    """Merge by normalized source row; primary wins unless fallback is richer."""
    merged: Dict[str, Any] = {}
    order: List[str] = []
    anonymous = 0
    for fact in list(primary) + list(fallback):
        key = _normalized_quote(getattr(fact, "source_quote", ""))
        if not key:
            anonymous += 1
            key = f"__anonymous_{anonymous}"
        current = merged.get(key)
        if current is None:
            merged[key] = fact
            order.append(key)
        elif _fact_score(fact) > _fact_score(current):
            merged[key] = fact
    return [merged[key] for key in order]


def _find(header: List[str], *markers: str) -> int:
    matches = _find_all(header, *markers)
    return matches[0] if matches else -1


def _find_all(header: List[str], *markers: str) -> List[int]:
    return [
        idx
        for idx, title in enumerate(header)
        if any(marker in title for marker in markers)
    ]


def _numeric_candidates(
    cells: List[str],
    header: List[str],
    *,
    excluded: set[int],
) -> List[tuple[int, float]]:
    """Numbers eligible for arithmetic quantity/price/total proof."""
    disallowed = ("код", "окпд", "№", "п/п", "поз", "индекс")
    out: List[tuple[int, float]] = []
    for idx, cell in enumerate(cells):
        if idx in excluded:
            continue
        title = header[idx] if idx < len(header) else ""
        if any(marker in title for marker in disallowed):
            continue
        if normalize_unit(cell)[0]:
            continue
        value = parse_number(cell)
        if value is not None:
            out.append((idx, value))
    return out


def _nearest_unit(
    cells: List[str],
    anchor: int,
    excluded: List[int],
) -> Optional[str]:
    excluded_set = set(excluded)
    candidates = []
    for idx, cell in enumerate(cells):
        if idx in excluded_set or not cell:
            continue
        normalized, _family = normalize_unit(cell)
        if normalized:
            candidates.append((abs(idx - anchor), idx, cell))
    return min(candidates)[2] if candidates else None


def _trailing_qty_unit(cells: List[str]) -> tuple[Optional[float], Optional[str]]:
    """Recover merged-header layouts where unit+qty occupy the row tail."""
    unit_index = None
    unit_raw = None
    for idx in range(len(cells) - 1, -1, -1):
        normalized, _family = normalize_unit(cells[idx])
        if normalized:
            unit_index = idx
            unit_raw = cells[idx]
            break
    if unit_index is None:
        return None, None
    for value in cells[unit_index + 1:]:
        quantity = parse_number(value)
        if quantity is not None:
            return quantity, unit_raw
    return None, unit_raw


def _cell(cells: List[str], idx: int) -> str:
    return cells[idx] if 0 <= idx < len(cells) else ""
