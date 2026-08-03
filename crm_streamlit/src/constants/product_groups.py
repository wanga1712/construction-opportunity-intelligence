"""Товарные направления для закупочного контура CRM."""
from __future__ import annotations

from src.services.object_models import ObjectViewItem


PRODUCT_GROUP_OPTIONS = (
    ("flooring", "Напольные покрытия"),
    ("self_leveling_floors", "Наливные / промышленные полы"),
    ("lighting", "Светотехника"),
    ("curbstone", "Бордюрный камень"),
    ("drainage", "Водоотвод"),
    ("waterproofing", "Гидроизоляция"),
    ("composites", "Композиты"),
    ("computers", "Компьютеры / ИТ"),
)

PRODUCT_GROUP_KEYWORDS = {
    "flooring": (
        "линолеум", "пвх", "плитка пвх", "ковролин", "покрыти", "полы",
        "пола", "напольн", "наливн", "спортивное покрытие", "паркет",
        "ламинат", "каучуков", "резиновое покрытие",
    ),
    "self_leveling_floors": (
        "наливной пол", "наливные полы", "наливное покрытие", "наливные покрытия",
        "промышленный пол", "промышленные полы", "промышленное покрытие",
        "эпоксидный пол", "полиуретановый пол", "полимерный пол",
        "износостойкое покрытие пола", "беспылевое покрытие",
    ),
    "lighting": (
        "светодиодный светильник", "led светильник", "лед светильник",
        "светодиодная панель", "световая панель", "led панель",
        "светотехническое оборудование", "осветительное оборудование",
        "система светодиодного освещения", "система искусственного освещения",
        "уличный светодиодный", "консольный светильник", "тоннельный светильник",
        "опора освещения", "опора наружного освещения",
        "аварийный светодиодный", "эвакуационный светильник", "блок аварийного питания",
        "промышленный светодиодный", "складской светодиодный",
        "архитектурное освещение", "фасадный светильник",
        "светодиодный прожектор", "даунлайт", "линейный светодиодный",
        "varton", "вартон", "пылевлагозащищенный светильник",
        "наружное освещение", "уличное освещение", "тоннельное освещение",
    ),
    "curbstone": (
        "бордюр", "бортовой камень", "бортов", "поребрик", "бордюрный камень",
    ),
    "drainage": (
        "водоотвод", "дренаж", "лоток", "лотки", "дождеприем",
        "ливнев", "водоотвед", "канализац", "коллектор",
    ),
    "waterproofing": (
        "гидроизоляц", "подвал", "подземн", "паркинг", "фундамент", "цоколь",
        "тоннел", "путепровод", "мост", "эстакад", "коллектор",
        "мембран", "инъектир", "инъекцир", "протеч",
    ),
    "composites": (
        "композит", "стеклопласт", "полимерпесчан", "полимер-композит",
        "пешеходный мост", "путепровод", "эстакад", "мостовое сооружение",
        "настил", "перила", "огражден", "лестничный сход",
    ),
    "computers": (
        # Title keywords are secondary; primary routing is OKPD 26.20* (see computer_okpd.py).
        "ноутбук", "моноблок", "системный блок", "рабочая станция",
        "мфу", "персональный компьютер",
    ),
}


def product_group_labels(codes: set[str]) -> list[str]:
    labels = {code: label for code, label in PRODUCT_GROUP_OPTIONS}
    return [labels[code] for code, _label in PRODUCT_GROUP_OPTIONS if code in codes]


def detect_product_groups_from_text(text: str) -> set[str]:
    """Heuristic product interest from free text (radar / early signals)."""
    hay = (text or "").lower()
    found: set[str] = set()
    if not hay:
        return found
    for code, keywords in PRODUCT_GROUP_KEYWORDS.items():
        if any(keyword in hay for keyword in keywords):
            found.add(code)
    return found


def detect_product_groups(item: ObjectViewItem) -> set[str]:
    """Лёгкая первичная детекция товарных возможностей (радар / эвристика).

    В закупочном контуре вкладки строятся по confirmed match groups,
    см. docs_match_preview.confirmed_product_groups.
    """
    text = " ".join(
        str(value or "")
        for value in (
            item.name,
            item.address,
            item.search_text,
            item.balance_holder,
            item.customer_name,
            item.contractor_name,
            item.expertise_planner,
        )
    )
    return detect_product_groups_from_text(text)
