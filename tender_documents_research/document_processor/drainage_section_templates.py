"""DRAINAGE_SECTION_TEMPLATES_V1 — обёртка над общим sheet-движком.

Drainage-оценки в текущих данных не содержат текстовых маркеров разделов,
поэтому основной контейнер — `page_or_sheet` (OCR `page_N_table_M`) или лист
xlsx. Если маркер «Раздел/Глава/Секция/Участок/Лот N» появится, он имеет
приоритет. Identity включает лист или номер документа.

Строки без маркера и без страницы — честный RESIDUE; numeric fake names
отбрасываются; в сумму только canonical summarizable-материалы.
Модуль read-only.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from .sheet_section_templates import (
    COVERAGE_MIN,
    SheetMarker as DrainageMarker,
    build_sheet_sections,
    parse_sheet_marker,
)

DRAINAGE_CODE_PREFIX = "drainage"
TEMPLATE_VERSION = "drainage_section_templates_v1"


def parse_drainage_marker(*texts: Any) -> Optional[DrainageMarker]:
    return parse_sheet_marker(*texts)


def build_drainage_sections(
    rows: Sequence[Dict[str, Any]],
    *,
    coverage_min: float = COVERAGE_MIN,
    page_fallback: bool = True,
) -> Dict[str, Any]:
    return build_sheet_sections(
        rows,
        prefix=DRAINAGE_CODE_PREFIX,
        template=TEMPLATE_VERSION,
        coverage_min=coverage_min,
        page_fallback=page_fallback,
    )
