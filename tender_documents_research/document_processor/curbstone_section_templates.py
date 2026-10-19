"""CURBSTONE_SECTION_TEMPLATES_V1 — обёртка над общим sheet-движком.

Маркеры «Раздел/Глава/Секция/Участок/Лот N <Название>», identity с листом или
номером документа, fallback `page_or_sheet` для OCR, numeric fake names
отбрасываются, строки без маркера/страницы — честный RESIDUE.

Логика вынесена в `sheet_section_templates`, чтобы curbstone и drainage
не дублировали код. Модуль read-only.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from .sheet_section_templates import (
    COVERAGE_MIN,
    SheetMarker as CurbstoneMarker,
    build_sheet_sections,
    parse_sheet_marker,
)

CURBSTONE_CODE_PREFIX = "curbstone"
TEMPLATE_VERSION = "curbstone_section_templates_v1"


def parse_curbstone_marker(*texts: Any) -> Optional[CurbstoneMarker]:
    return parse_sheet_marker(*texts)


def build_curbstone_sections(
    rows: Sequence[Dict[str, Any]],
    *,
    coverage_min: float = COVERAGE_MIN,
    page_fallback: bool = True,
) -> Dict[str, Any]:
    return build_sheet_sections(
        rows,
        prefix=CURBSTONE_CODE_PREFIX,
        template=TEMPLATE_VERSION,
        coverage_min=coverage_min,
        page_fallback=page_fallback,
    )
