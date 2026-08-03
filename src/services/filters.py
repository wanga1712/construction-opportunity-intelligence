"""
Фильтрация списка компаний (та же логика, что в DesignersRegistryWidget).
"""
from typing import List, Optional

from modules.crm.analytics.analytics_models import DesignerAnalytics


def filter_companies(
    companies: List[DesignerAnalytics],
    search: str = "",
    region: Optional[str] = None,
    grade: Optional[str] = None,
) -> List[DesignerAnalytics]:
    """Отфильтровать компании по поиску, региону и классу."""
    query = search.strip().lower()
    result: List[DesignerAnalytics] = []
    for d in companies:
        if region and d.region != region:
            continue
        if grade and d.company_grade != grade:
            continue
        if query and query not in d.full_name.lower() and query not in d.inn:
            continue
        result.append(d)
    return result
