"""Deterministic goods/works + count-unit gate for embedded facts.

This module lives in the document runtime so the worker daemon does not need to
import the CRM package.  It mirrors the business rules from CRM's
``works_vs_goods_service`` and ``good_supply_facts_service`` for facts that are
worth persisting to ``structured_entities``:

  * the row must look like a good, not a work item;
  * aggregate/section headers are never commercial positions;
  * the unit must be a countable unit (PCS/SET/UNIT/...), not bulk material;
  * quantity must be a whole count;
  * a line total must exist so the card has a value to show.
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional

GOODS_ENTITY_TYPES = {"PRODUCT", "MATERIAL", "EQUIPMENT", "TECHNOLOGY"}
WORK_ENTITY_TYPES = {"WORK"}

GOODS = "GOODS"
WORK = "WORK"

COUNT_UNITS = frozenset(
    {"PCS", "UNIT", "SET", "PACK", "ROLL", "BAG", "SHEET", "PAIR"}
)

_WORK_NAME_RE = re.compile(
    r"^\s*("
    r"устройств|разборк|демонтаж|монтаж|установк|фрезеров|подсыпк|устранени|"
    r"планиров|уплотнен|разметк|укладк|засыпк|разработк|прокладк|восстановлен|"
    r"ремонт|окраск|штукатурк|кладк|сверлени|нанесени|шлифовк|кристаллизац|"
    r"замен|сняти|пробивк|нарезк|укреплен|прочистк|бурени|сварк|содержани|"
    r"переустройств|перевозк|погрузк|вывоз|демонта|"
    r"обсыпк|отсыпк|срезк|корчевк|рытье|профилиров|обеспылив|розлив|планировк|"
    r"рекультивац|засев|посев|посадк|уход|демаркиров|обустройств|обработк"
    r"|резк|испытан|замер|проверк|расход|организац|ликвидац|перемещен|наращиван|вырубк|заделк|креплен|"
    r"сооружен|усилен|погруж|извлечен|шпунтов|огражден"
    r")",
    re.IGNORECASE,
)
_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+(?:[.,]\d+)*(?:[.)])?\s+")
_AGGREGATE_RE = re.compile(
    r"^\s*(итого|всего|стоимость|ндс|раздел|глава|\d+(?:\.\d+)*\s+\S)",
    re.IGNORECASE,
)


def classify_fact_kind(*, entity_type: Optional[str] = None, name: Optional[str] = None) -> str:
    kind = str(entity_type or "").strip().upper()
    if kind in WORK_ENTITY_TYPES:
        return WORK
    text = _NUMBER_PREFIX_RE.sub("", str(name or ""))
    if _WORK_NAME_RE.match(text):
        return WORK
    return GOODS


def is_aggregate_name(name: Optional[str]) -> bool:
    return bool(_AGGREGATE_RE.match(str(name or "")))


def _fractional_count_quantity(quantity_value: Any, unit_normalized: Optional[str]) -> bool:
    unit = str(unit_normalized or "").upper()
    if unit not in COUNT_UNITS or quantity_value is None:
        return False
    try:
        quantity = float(quantity_value)
    except (TypeError, ValueError):
        return True
    return not math.isclose(quantity, round(quantity), rel_tol=0.0, abs_tol=1e-9)


def is_confident_count_goods(fact: Any) -> bool:
    """True when a fact is a countable good that the CRM card can display."""
    name = (
        getattr(fact, "product_name_raw", "")
        or getattr(fact, "product_name_normalized", "")
        or ""
    )
    if classify_fact_kind(entity_type=getattr(fact, "entity_type", "PRODUCT"), name=name) != GOODS:
        return False
    if is_aggregate_name(name):
        return False
    unit = str(getattr(fact, "unit_normalized", "") or "").upper()
    if unit not in COUNT_UNITS:
        return False
    quantity = getattr(fact, "quantity_value", None)
    if quantity is None or _fractional_count_quantity(quantity, unit):
        return False
    if getattr(fact, "line_total_value", None) is None:
        return False
    return True
