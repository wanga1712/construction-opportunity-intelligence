"""Форматирование дат и статуса закупки для карточки объекта."""
from datetime import date, datetime

from src.services.object_lifecycle import is_awarded_registry  # re-export


def fmt_date(val) -> str:
    """Дата в формате ДД.ММ.ГГГГ."""
    if not val:
        return "—"
    if isinstance(val, datetime):
        return val.strftime("%d.%m.%Y")
    if isinstance(val, date):
        return val.strftime("%d.%m.%Y")
    text = str(val).strip()
    if len(text) >= 10 and text[4:5] == "-":
        parts = text[:10].split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return text[:10]
