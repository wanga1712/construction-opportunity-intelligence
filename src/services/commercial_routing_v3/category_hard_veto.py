"""Deterministic hard vetoes: titles that can never belong to a product category.

Cheap, pre-model guard for obvious misclassifications (e.g. road wear-layer
works landing in ``lighting``). No model calls, no DB access — pure function.
"""
from __future__ import annotations

from typing import Optional

# Resurfacing/pavement works: these exclude product categories that carry no
# such content at all (e.g. lighting).
_PAVEMENT_WORKS = (
    "слоёв износа", "слоя износа", "слой износа",
    "дорожной одежд", "дорожная одежда",
    "ямочный ремонт", "устройство асфальт", "асфальтобетон",
    "устройство покрытия", "нанесение дорожной разметки", "дорожная разметка",
    "трамвайных путей", "трамвайные пути", "железнодорожных путей",
    "ремонт путей", "путевое хозяйство", "верхнее строение пути",
    "отсыпк", "щебн", "щебён", "щебеночн",
    "разметк", "элементов обустройства", "обустройства автомобильных дорог",
)

# Simple road-building (gravel/asphalt) with no structural element at all.
_SIMPLE_ROAD = (
    "щебеночн", "щебён", "гравийн", "грунтов", "асфальт", "слоёв износа",
    "дорожной одежд", "ямочный ремонт", "разметк",
    "неровност", "лежачего полицейского", "дорожных знак", "дорожные знак",
    "знаков", "обустройств",
    "дорожного покрытия", "устранение повреждений", "повреждений дорожного",
    "отсыпк",
)

# Stops/road barriers works: not lighting (explicitly named elements).
_STOPS_BARRIERS = ("остановочн", "дорожных огражден", "дорожные огражден", "обустройств")

# Broad road/bridge works: a road product category (curbstone) is implausible
# unless the title names it explicitly.
_ROAD_OBJECT_WORKS = _PAVEMENT_WORKS + (
    "содержанию линий наружного освещения",
    "аэродром", "взлётно-посадочн", "взлетно-посадочн", "рулежн", "перрон",
)

# Which works-group applies to which category, with the category's own positive
# markers (if any marker is present the row is not vetoed).
_URBAN_IMPROVEMENT = ("благоустройств", "озеленен", "детская площадк", "детской площадк")
_ROAD_REPAIR = (
    "ремонт автомобильной дороги", "капитальный ремонт автомобильной дороги",
    "реконструкция автомобильной дороги", "строительство автомобильной дороги",
    "содержание автомобильных дорог", "автомобильн", "автодорог",
)

_CATEGORY_RULES = {
    "lighting": (_PAVEMENT_WORKS + _STOPS_BARRIERS, ("светильник", "освещен", "светодиод", "лампа",
                                   "светотех", "прожектор", "люминесцент", "опора освещен")),
    "curbstone": (_ROAD_OBJECT_WORKS, ("бордюр", "бортовой камень", "бортовых камн")),
    "waterproofing": (_PAVEMENT_WORKS + _URBAN_IMPROVEMENT + _ROAD_REPAIR,
                      ("гидроизол", "мембран", "оклеечн", "обмазочн",
                       "инъекцион", "праймер", "герметик")),
    "composite_structures": (_SIMPLE_ROAD,
                             ("композит", "стеклопластик", "перила", "огражден",
                              "решетчат", "лоток", "профиль", "конструкц")),
    "drainage_water_management": (_PAVEMENT_WORKS + _SIMPLE_ROAD,
                                  ("водоотвед", "дренаж", "ливнев", "колодец",
                                   "трубопровод", "лоток")),
}

_CATEGORY_MARKERS = {
    code: markers for code, (_group, markers) in _CATEGORY_RULES.items()
}

_LEGACY_MARKERS = {
    "lighting": ("светильник", "освещен", "светодиод", "лампа", "светотех",
                 "прожектор", "люминесцент", "опора освещен", "кронштейн"),
    "flooring": ("полы", "покрытие пола", "наливн", "линолеум", "паркет", "плитк"),
    "curbstone": ("бордюр", "бортовой камень", "бортовых камн"),
}

REASON_ROAD_WORKS_OUT_OF_CATEGORY = "ROAD_WORKS_OUT_OF_CATEGORY"
REASON_SERVICE_MAINTENANCE_OUT_OF_SCOPE = "SERVICE_MAINTENANCE_OUT_OF_SCOPE"

# Global out-of-scope markers: maintenance/service contracts for engineering
# communications are not commercial opportunities for any category.
_GLOBAL_OUT_OF_SCOPE = (
    "обслуживание инженерных коммуникаций",
    "техническое обслуживание инженерн",
    "техническое обслуживание коммуникац",
    "текущий ремонт и техническое обслуживание",
    "обслуживание и ремонт инженерных коммуникаций",
    "организации дорожного движения", "проект организации дорожного движения",
    "транспортн", "безопасности дорожного движения",
)


def hard_veto_reason(category_code: Optional[str], title: Optional[str],
                     okpd_name: Optional[str] = None) -> Optional[str]:
    """Return a veto reason when the title can never belong to the category."""
    category = str(category_code or "").strip().lower()
    text = f"{title or ''} {okpd_name or ''}".strip().lower()
    if not text:
        return None
    if any(marker in text for marker in _GLOBAL_OUT_OF_SCOPE):
        return REASON_SERVICE_MAINTENANCE_OUT_OF_SCOPE
    if not category:
        return None
    rule = _CATEGORY_RULES.get(category)
    if rule is None:
        return None
    works_markers, own_markers = rule
    if not any(marker in text for marker in works_markers):
        return None
    if any(marker in text for marker in own_markers):
        return None
    return REASON_ROAD_WORKS_OUT_OF_CATEGORY
