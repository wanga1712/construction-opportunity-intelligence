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
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

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
) -> List[Any]:
    """DIRECT facts via explicit column mapping (never price-as-quantity)."""
    from document_processor.embedded_extraction import (
        ExtractedFact,
        extract_facts,
        fingerprint,
        normalize_name,
        normalize_unit,
        parse_number,
        split_quantity_unit,
    )

    module = _load_module()
    facts: List[ExtractedFact] = []
    seen: set = set()
    if module is not None:
        try:
            tables = module.extract_tables([str(path)]) or {}
        except Exception:
            tables = {}
        for kind in ("spec", "tech", "requirements"):
            for row in tables.get(kind, []) or []:
                cells = [str(c).strip() for c in (row.get("cells") or [])]
                header = [str(h).strip().lower() for h in (row.get("header") or [])]
                if not any(cells):
                    continue
                i_name = _find(header, "наименован", "характеристик", "параметр", "показател", "товар")
                i_unit = _find(header, "единиц", "ед. изм", "ед.изм", "ед ")
                i_qty = _find(header, "кол-во", "количество", "кол.")
                i_price = _find(header, "цена")
                i_total = _find(header, "стоимост", "сумма")
                name = _cell(cells, i_name)
                if not name:
                    name = max((c for c in cells if sum(ch.isalpha() for ch in c) >= 3),
                               key=len, default="")
                if not name or sum(ch.isalpha() for ch in name) < 3:
                    continue
                # quantity strictly from the quantity column (fallback: a cell
                # carrying qty+unit), never from the price/total columns.
                qty = unit_raw = None
                if 0 <= i_qty < len(cells):
                    parsed = split_quantity_unit(cells[i_qty])
                    if parsed:
                        qty, unit_raw = parsed[0], parsed[1]
                    else:
                        qty = parse_number(cells[i_qty])
                if 0 <= i_unit < len(cells) and _cell(cells, i_unit):
                    unit_raw = _cell(cells, i_unit)
                if qty is None:
                    for idx, cell in enumerate(cells):
                        if idx in {i_price, i_total, i_name}:
                            continue
                        parsed = split_quantity_unit(cell)
                        if parsed and parsed[2]:
                            qty, unit_raw = parsed[0], parsed[1]
                            break
                unit_norm, family = normalize_unit(unit_raw)
                unit_price = parse_number(_cell(cells, i_price)) if i_price >= 0 else None
                line_total = parse_number(_cell(cells, i_total)) if i_total >= 0 else None
                # A quantity without a recognized unit is a column-mapping error,
                # not a fact (e.g. row index captured as quantity).
                if qty is not None and unit_norm is None:
                    qty = None
                if qty is None and unit_price is None and line_total is None:
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
                )
                fact.entity_fingerprint = fingerprint(fact, str(fact.row_or_line))
                if fact.entity_fingerprint in seen:
                    continue
                seen.add(fact.entity_fingerprint)
                facts.append(fact)

    if facts:
        return facts
    # Fallback: flattened template text through the generic row parser.
    text = build_direct_text(path)
    if not text:
        return []
    return extract_facts(
        procurement_id=procurement_id,
        category_code=category_code,
        document_name=document_name,
        text=text,
        line_meta=None,
        source_document_id=source_document_id,
        physical_key=physical_key,
        category_keywords=(),
    )


def _find(header: List[str], *markers: str) -> int:
    for i, h in enumerate(header):
        if any(m in h for m in markers):
            return i
    return -1


def _cell(cells: List[str], idx: int) -> str:
    return cells[idx] if 0 <= idx < len(cells) else ""
