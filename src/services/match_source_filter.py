"""MATCH_TERM_HYGIENE_V1 / 3A — source-filter для находок.

`document_match_details` исторически содержит матчи из документов участника,
требований к заявке и порядка оценки. Такие матчи не являются коммерческими
фактами: `прожектор`, `проспект`, `управлен`, `солидтех` и т.п. появляются из
шаблонного текста заявки, а не из сметы/ТЗ.

Модуль read-only и только классифицирует имя файла:

  RESEARCHABLE      — смета, ЛСР, ведомость объёмов, ТЗ, спецификация,
                      расчёт/обоснование НМЦК, дефектная ведомость, КС-2/3;
  NON_RESEARCHABLE  — требования к заявке, порядок/критерии оценки,
                      протокол, разъяснение, жалоба;
  UNKNOWN           — всё остальное (не выдумываем).

Карточка показывает RESEARCHABLE и UNKNOWN, NON_RESEARCHABLE скрывает.
Сами строки в БД не удаляются.
"""
from __future__ import annotations

from typing import Any

RESEARCHABLE = "RESEARCHABLE"
NON_RESEARCHABLE = "NON_RESEARCHABLE"
UNKNOWN = "UNKNOWN"

#: Порядок важен: non-researchable проверяется первым.
NON_RESEARCHABLE_PATTERNS = (
    "требования к содержанию",
    "требования к составу",
    "требования к заявке",
    "заявка на участие",
    "заявке на участие",
    "инструкция по",
    "порядок рассмотрения",
    "порядок оценки",
    "критерии оценки",
    "оценка заявок",
    "протокол",
    "разъяснени",
    "жалоб",
)

RESEARCHABLE_PATTERNS = (
    "смет",
    "лср",
    "локальн",
    "ведомост",
    "спецификац",
    "техническое задание",
    "техзадани",
    "тз",
    "расчёт нмцк",
    "расчет нмцк",
    "обоснование нмцк",
    "нмцк",
    "дефектн",
    "форма 4",
    "кс-2",
    "кс-3",
    "описание объекта закупки",
)


def classify_match_source(file_name: Any) -> str:
    """Класс источника матча по имени файла."""
    name = str(file_name or "").strip().lower()
    if not name:
        return UNKNOWN
    if any(p in name for p in NON_RESEARCHABLE_PATTERNS):
        return NON_RESEARCHABLE
    if any(p in name for p in RESEARCHABLE_PATTERNS):
        return RESEARCHABLE
    return UNKNOWN


def is_non_researchable(file_name: Any) -> bool:
    return classify_match_source(file_name) == NON_RESEARCHABLE
