"""Уровни полноты данных объекта и цвета карточек."""
from typing import Optional

OBJECT_QUALITY_TIERS = (
    ("gold", "Золотые"),
    ("silver", "Серебряные"),
    ("bronze", "Бронзовые"),
    ("wood", "Деревянные"),
)

TIER_LABELS = {code: label for code, label in OBJECT_QUALITY_TIERS}

TIER_BORDER_COLORS = {
    "gold": "#D4A017",
    "silver": "#7A8A96",
    "bronze": "#C06A2E",
    "wood": "#8B6B45",
}

TIER_BADGE_COLORS = {
    "gold": ("#FFE082", "#6B4A00"),
    "silver": ("#CFD8DC", "#37474F"),
    "bronze": ("#FFCC80", "#5D3208"),
    "wood": ("#D7CCC8", "#3E2723"),
}

# Фон всей превью-карточки по медали
TIER_CARD_BG = {
    "gold": "linear-gradient(135deg, #FFF8E1 0%, #FFECB3 55%, #FFE082 100%)",
    "silver": "linear-gradient(135deg, #F5F7FA 0%, #ECEFF1 55%, #CFD8DC 100%)",
    "bronze": "linear-gradient(135deg, #FFF3E0 0%, #FFE0B2 55%, #FFCC80 100%)",
    "wood": "linear-gradient(135deg, #EFEBE9 0%, #D7CCC8 55%, #BCAAA4 100%)",
}


def resolve_quality_tier(
    *,
    doc_matches: int = 0,
    expertise_number: Optional[str] = None,
    customer_inn: Optional[str] = None,
    contractor_inn: Optional[str] = None,
) -> str:
    """Определить уровень карточки по доступным связям."""
    if doc_matches > 0:
        return "bronze"
    if expertise_number:
        return "bronze"
    if customer_inn and contractor_inn:
        return "wood"
    return "wood"
