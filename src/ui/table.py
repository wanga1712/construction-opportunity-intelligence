"""
Сборка DataFrame для таблицы компаний.
"""
import pandas as pd

from modules.crm.analytics.analytics_models import DesignerAnalytics
from modules.crm.analytics.designer_profile_constants import (
    COMPANY_CATEGORY_LABELS,
    REGISTRY_LABELS,
)
from src.ui.company_title import get_company_display_name


def companies_to_dataframe(companies: list[DesignerAnalytics]) -> pd.DataFrame:
    """Преобразовать список компаний в таблицу для st.dataframe."""
    rows = []
    for d in companies:
        rows.append({
            "★": "★" if d.is_favorite else "",
            "ИНН": d.inn,
            "Название": get_company_display_name(d),
            "Регион": d.region,
            "Жилое": d.segments.residential,
            "Соц.": d.segments.social,
            "Комм.": d.segments.commercial,
            "Другое": d.segments.other,
            "Всего": d.total_objects,
            "Категория": COMPANY_CATEGORY_LABELS.get(d.company_category or "", "—"),
            "Класс": d.company_grade or "—",
            "Реестр": REGISTRY_LABELS.get(d.registry or "", "—"),
        })
    return pd.DataFrame(rows)
