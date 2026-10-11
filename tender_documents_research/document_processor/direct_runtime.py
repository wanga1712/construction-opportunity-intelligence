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
    from document_processor.embedded_extraction import extract_facts

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
