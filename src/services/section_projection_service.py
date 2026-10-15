"""SECTION_LEVEL_NORMALIZATION_V1 (Phase 3) — детерминированная проекция разделов.

Чистая логика без БД: группирует строки `structured_entities` в
«раздел → сумма раздела → материалы» и отдельный «остаток» (RESIDUE / NULL).

Сумма показывается только тогда, когда ей можно доверять:

    SECTION_TOTAL / COMPUTED_SUM   -> число
    COMPUTED_SUM_UNRELIABLE        -> числа НЕТ, только «сумма требует проверки»

Никакого влияния на scoring/medal/queue. Порядок детерминирован: сортировка по
`section_code`, внутри раздела — порядок материалов из запроса.
"""
from __future__ import annotations

from typing import Any, Dict, List

RESIDUE_PREFIX = "RESIDUE"
TRUSTED_SOURCES = ("SECTION_TOTAL", "COMPUTED_SUM")
UNRELIABLE_SOURCES = ("COMPUTED_SUM_UNRELIABLE",)
TOTAL_NEEDS_REVIEW = "сумма требует проверки"

#: сколько материалов показывать внутри одного раздела (детерминированный срез)
SECTION_MATERIALS_PER_SECTION = 25
#: сколько строк «остатка» показывать
RESIDUE_ROWS_LIMIT = 50


def is_residue(section_code: Any) -> bool:
    """Пустой section или явный RESIDUE -> «остаток»."""
    text = str(section_code or "").strip()
    return (not text) or text.upper().startswith(RESIDUE_PREFIX)


def total_state(total_value: Any, total_source: Any) -> str:
    """`confirmed` | `unreliable` | `unknown` для суммы раздела."""
    source = str(total_source or "").strip().upper()
    if source in UNRELIABLE_SOURCES:
        return "unreliable"
    if source in TRUSTED_SOURCES and total_value is not None:
        return "confirmed"
    return "unknown"


def build_section_projection(
    section_rows: List[Dict[str, Any]],
    residue_rows: List[Dict[str, Any]],
    residue_total: Any = None,
) -> Dict[str, Any]:
    """Собрать разделы и «остаток» из уже загруженных строк (детерминированно).

    `section_rows` — строки с непустым `section_code` (материалы; в каждой строке
    денормализованы section-поля и `material_count`). `residue_rows` — строки без
    section identity (или с `RESIDUE*`).
    `residue_total` — полное число строк «остатка» (если известно из запроса),
    иначе берётся длина выборки.

    Раздел — контейнер для найденного материала, а не самостоятельная категория:
    разделы БЕЗ релевантных материалов (`relevant_count == 0`) в проекцию не
    попадают. Их количество возвращается в `sections_skipped_empty` — только для
    аудита, в UI это не выводится.
    """
    buckets: Dict[str, Dict[str, Any]] = {}
    for row in section_rows or []:
        code = str(row.get("section_code") or "")
        if is_residue(code):
            continue
        bucket = buckets.get(code)
        if bucket is None:
            bucket = {
                "section_code": code,
                "section_name": row.get("section_name") or code,
                "page_or_sheet": row.get("page_or_sheet"),
                "total_value": row.get("section_total_price_value"),
                "total_raw": row.get("section_total_price_raw"),
                "total_source": row.get("section_total_source"),
                "material_count": row.get("material_count") or 0,
                "relevant_count": row.get("relevant_count"),
                "materials": [],
            }
            buckets[code] = bucket
        bucket["materials"].append(row)

    sections: List[Dict[str, Any]] = []
    skipped_empty = 0
    for code in sorted(buckets):
        bucket = buckets[code]
        bucket["material_count"] = max(
            int(bucket.get("material_count") or 0), len(bucket["materials"])
        )
        relevant = bucket.get("relevant_count")
        if relevant is None:
            relevant = len(bucket["materials"])
        if int(relevant) <= 0:
            skipped_empty += 1
            continue
        bucket["total_state"] = total_state(bucket.get("total_value"), bucket.get("total_source"))
        sections.append(bucket)

    residue: List[Dict[str, Any]] = []
    for row in residue_rows or []:
        if not is_residue(row.get("section_code")):
            continue
        residue.append(row)

    return {
        "sections": sections,
        "sections_skipped_empty": skipped_empty,
        "residue": {
            "rows": residue,
            "count": int(residue_total) if residue_total is not None else len(residue),
        },
    }
