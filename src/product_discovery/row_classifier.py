"""Row type classifier for estimate and BOQ line items."""

from __future__ import annotations

import re
from typing import Optional

from src.product_discovery.dto import RowType, UnitCategory
from src.product_discovery.unit_normalizer import normalize_unit


# Work verbs and activity indicators
RE_WORK_TERMS = re.compile(
    r"\b(монтаж\w*|установк\w*|прокладк\w*|устройств\w*|демонтаж\w*|разборк\w*|"
    r"очистк\w*|покраск\w*|окраск\w*|сборк\w*|испытан\w*|настройк\w*|пусконалад\w*|"
    r"выполнени\w*\s+работ|разработк\w*|бурени\w*|забивк\w*|погружени\w*|"
    r"засыпк\w*|планировк\w*|срезк\w*|шпаклевк\w*|штукатурк\w*|кладк\w*|заливк\w*|"
    r"сварк\w*|стяжк\w*|грунтовк\w*|гидроизоляци\w*|теплоизоляци\w*)\b",
    re.IGNORECASE,
)

RE_SERVICE_TERMS = re.compile(
    r"\b(услуг\w*|техническ\w*\s+обслуживан\w*|эксплуатац\w*|надзор\w*|аренд\w*|"
    r"перевозк\w*|доставк\w*|погрузочн\w*|разгрузочн\w*|утилизац\w*|экспертиз\w*|"
    r"освидетельствован\w*|паспортизац\w*)\b",
    re.IGNORECASE,
)

RE_MACHINE_TERMS = re.compile(
    r"\b(автовышк\w*|автогидроподъемник\w*|кран\s+автомобильн\w*|экскаватор\w*|"
    r"бульдозер\w*|каток\w*|компрессор\w*|трактор\w*|самосвал\w*|погрузчик\w*|"
    r"маш\.\s*час|машино-час)\b",
    re.IGNORECASE,
)

RE_EQUIPMENT_TERMS = re.compile(
    r"\b(светильник\w*|прожектор\w*|лифт\w*|насос\w*|трансформатор\w*|шкаф\s+управлен\w*|"
    r"щит\w*|генератор\w*|вентилятор\w*|кондиционер\w*|сервер\w*|котел\w*|горелк\w*|"
    r"клапан\w*|задвижк\w*|электродвигател\w*)\b",
    re.IGNORECASE,
)

RE_MATERIAL_TERMS = re.compile(
    r"\b(кабел\w*|провод\w*|труб\w*|опор\w*|кронштейн\w*|болт\w*|гайк\w*|шайб\w*|"
    r"смес\w*|бетон\w*|раствор\w*|песок\w*|щебень\w*|арматур\w*|грунтовк\w*|"
    r"кирпич\w*|плит\w*|шприц\w*|перчатк\w*|бинт\w*|лент\w*)\b",
    re.IGNORECASE,
)


def classify_row(
    text: str,
    unit: Optional[str] = None,
    total_amount: Optional[float] = None,
) -> RowType:
    """Classifies table row into RowType (PRODUCT, WORK, SERVICE, MACHINE, MATERIAL, EQUIPMENT)."""
    if not text or not text.strip():
        return RowType.UNKNOWN

    raw = text.strip()
    u_cat = normalize_unit(unit)

    # 1. Machinery check
    if RE_MACHINE_TERMS.search(raw) or "маш.час" in (unit or "").lower():
        return RowType.MACHINE

    # 2. Service check
    if RE_SERVICE_TERMS.search(raw):
        return RowType.SERVICE

    # 3. Work check (check if row starts with action/work term or contains heavy work verb)
    work_match = RE_WORK_TERMS.search(raw)
    equipment_match = RE_EQUIPMENT_TERMS.search(raw)
    material_match = RE_MATERIAL_TERMS.search(raw)

    if work_match:
        # If work match is at start or precedes noun without specific catalog code
        w_start = work_match.start()
        if w_start == 0 or (equipment_match is None and material_match is None):
            return RowType.WORK
        # If phrase is like "Монтаж светильников..." -> WORK
        first_words = raw.split()[:2]
        if any(RE_WORK_TERMS.match(w) for w in first_words):
            return RowType.WORK

    # 4. Equipment check
    if equipment_match:
        return RowType.EQUIPMENT

    # 5. Material check
    if material_match:
        return RowType.MATERIAL

    # 6. Default to PRODUCT if measured in PCS/SET, or MATERIAL if measured in LENGTH/AREA/WEIGHT
    if u_cat in (UnitCategory.PCS, UnitCategory.SET):
        return RowType.PRODUCT
    elif u_cat in (UnitCategory.LENGTH, UnitCategory.AREA, UnitCategory.WEIGHT, UnitCategory.VOLUME):
        return RowType.MATERIAL

    return RowType.PRODUCT
