"""Сортировка компаний для очереди и PDF-выгрузки."""
from typing import List, Optional, Tuple

from modules.crm.analytics.analytics_models import DesignerAnalytics
from modules.crm.analytics.designer_profile_constants import (
    COMPANY_CATEGORY_OTHER,
    GRADE_OTHER,
)

# A → B → C → без типа (не проектировщик/подрядчик) → E → … → D в конце
_TIER_A = 100
_TIER_B = 200
_TIER_C = 300
_TIER_UNSET_TYPE = 400
_TIER_E = 500
_TIER_OTHER_GRADE = 600
_TIER_MISC = 700
_TIER_D = 900

_TIER_SECTION_LABELS = {
    _TIER_A: "Класс A",
    _TIER_B: "Класс B",
    _TIER_C: "Класс C",
    _TIER_UNSET_TYPE: "Без категории (тип не установлен)",
    _TIER_E: "Класс E",
    _TIER_OTHER_GRADE: "Класс: другое",
    _TIER_MISC: "Прочие",
    _TIER_D: "Класс D",
}

_MAIN_COMPANY_TYPES = frozenset({"designer", "contractor", "designer_contractor"})


def _normalize_grade(grade: Optional[str]) -> Optional[str]:
    if grade is None:
        return None
    value = str(grade).strip()
    if not value or value in ("—", "-"):
        return None
    upper = value.upper()
    if upper == GRADE_OTHER.upper():
        return GRADE_OTHER
    if upper in ("A", "B", "C", "D", "E"):
        return upper
    return None


def is_company_type_other(company: DesignerAnalytics) -> bool:
    """Категория компании «Другое» — отдельная выгрузка."""
    return company.company_category == COMPANY_CATEGORY_OTHER


def is_unset_company_type(company: DesignerAnalytics) -> bool:
    """Не проектировщик, не подрядчик, не П-п — тип не установлен."""
    cat = company.company_category
    if not cat:
        return True
    return cat not in _MAIN_COMPANY_TYPES


def pdf_export_tier(company: DesignerAnalytics) -> int:
    """
    Порядок: A → B → C → без типа → E → D (последний).
    Категория «Другое» — через is_company_type_other, в основную очередь не входит.
    """
    grade = _normalize_grade(company.company_grade)

    if grade == "D":
        return _TIER_D
    if grade == "A":
        return _TIER_A
    if grade == "B":
        return _TIER_B
    if grade == "C":
        return _TIER_C
    if grade == "E":
        return _TIER_E
    if grade == GRADE_OTHER:
        return _TIER_OTHER_GRADE
    if is_unset_company_type(company):
        return _TIER_UNSET_TYPE
    if grade is None:
        return _TIER_MISC
    return _TIER_MISC


def pdf_export_grade_sort_key(company: DesignerAnalytics) -> Tuple[int, str, str]:
    return (
        pdf_export_tier(company),
        (company.full_name or "").lower(),
        company.inn,
    )


def grade_section_label(company: DesignerAnalytics) -> str:
    return _TIER_SECTION_LABELS.get(pdf_export_tier(company), "Прочие")


def sort_companies_for_pdf(companies: List[DesignerAnalytics]) -> List[DesignerAnalytics]:
    return sorted(companies, key=pdf_export_grade_sort_key)


def split_queue_for_export(
    companies: List[DesignerAnalytics],
) -> Tuple[List[DesignerAnalytics], List[DesignerAnalytics]]:
    """Разделить очередь: основная выгрузка и категория «Другое»."""
    main: List[DesignerAnalytics] = []
    other: List[DesignerAnalytics] = []
    for company in companies:
        if is_company_type_other(company):
            other.append(company)
        else:
            main.append(company)
    return sort_companies_for_pdf(main), sort_companies_for_pdf(other)


def load_queued_companies(service, inns: List[str]) -> List[DesignerAnalytics]:
    """Все компании из очереди (без сортировки по ИНН)."""
    return [c for inn in inns if (c := service.get_company(inn))]


def load_queued_companies_split(
    service, inns: List[str],
) -> Tuple[List[DesignerAnalytics], List[DesignerAnalytics]]:
    """Очередь: основной PDF и отдельно «Другое»."""
    return split_queue_for_export(load_queued_companies(service, inns))
