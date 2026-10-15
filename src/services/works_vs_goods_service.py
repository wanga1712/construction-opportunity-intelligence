"""WORKS_VS_GOODS_CONFIRMATION_V1 — «товар vs работа» для подтверждения категории.

Коммерческое правило: `confirmed_base` и «есть что поставить» считаются ТОЛЬКО по
товарным / материальным фактам. Работы подтверждением категории не являются
(кейс 29311: `lighting` подтверждён фрезерованием асфальта).

Сигналы:

  * `entity_type`: PRODUCT / MATERIAL / EQUIPMENT / TECHNOLOGY = GOODS, WORK = WORK;
  * НАЗВАНИЕ, начинающееся с глагола работ («Устройство…», «Фрезерование…»,
    «Подсыпка…», «Устранение…» и т.п.) = WORK. Это ключевой сигнал: embedded-экстрактор
    помечает ВСЁ как PRODUCT, поэтому тип здесь не различает (см. 29311);
  * агрегатные/шапочные строки (`_is_aggregate_name`) не являются подтверждением.

Ничего не пишет в БД; модуль используется слоем подтверждения и карточкой.
"""
from __future__ import annotations

import re
from typing import Optional

GOODS_ENTITY_TYPES = {"PRODUCT", "MATERIAL", "EQUIPMENT", "TECHNOLOGY"}
WORK_ENTITY_TYPES = {"WORK"}

GOODS = "GOODS"
WORK = "WORK"

#: Глаголы работ в начале названия позиции. Список расширен дорожными работами
#: (фрезерование, подсыпка, планировка, уплотнение, разметка), которых нет в
#: `embedded_extraction._WORK_ROW`, плюс строительные глаголы оттуда.
_WORK_NAME_RE = re.compile(
    r"^\s*("
    r"устройств|разборк|демонтаж|монтаж|установк|фрезеров|подсыпк|устранени|"
    r"планиров|уплотнен|разметк|укладк|засыпк|разработк|прокладк|восстановлен|"
    r"ремонт|окраск|штукатурк|кладк|сверлени|нанесени|шлифовк|кристаллизац|"
    r"замен|сняти|пробивк|нарезк|укреплен|прочистк|бурени|сварк|содержани|"
    r"переустройств|перевозк|погрузк|вывоз|демонта"
    r")",
    re.IGNORECASE,
)


def classify_fact_kind(*, entity_type: Optional[str] = None, name: Optional[str] = None) -> str:
    """`GOODS` | `WORK` для одного факта (детерминированно, без модели)."""
    kind = str(entity_type or "").strip().upper()
    if kind in WORK_ENTITY_TYPES:
        return WORK
    if _WORK_NAME_RE.match(str(name or "")):
        return WORK
    return GOODS


def is_goods(*, entity_type: Optional[str] = None, name: Optional[str] = None) -> bool:
    return classify_fact_kind(entity_type=entity_type, name=name) == GOODS
