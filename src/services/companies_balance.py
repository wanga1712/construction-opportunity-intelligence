"""Balance-holder segmentation helpers for ``CompaniesService``."""
from typing import List, Optional, Tuple

from modules.crm.analytics.analytics_models import DesignerAnalytics
from modules.crm.analytics.designer_profile_constants import is_visible_legal_status
from modules.crm.analytics.inn_normalize import normalize_inn


def companies_for_balance_holder(
    service, main_tab: str, housing_sub: Optional[str] = None,
) -> List[DesignerAnalytics]:
    result = []
    for company in service.all_companies:
        if not _is_candidate(company):
            continue
        main, housing = company_balance_segment(service, company)
        if main == main_tab and (main_tab != "housing" or not housing_sub or not housing or housing == housing_sub):
            result.append(company)
    return result


def unclassified_balance_holders(service) -> List[DesignerAnalytics]:
    return [
        company for company in service.all_companies
        if _is_candidate(company) and not company_balance_segment(service, company)[0]
    ]


def save_balance_holder_segment(
    service, profile_inn: str, main_tab: Optional[str], housing_sub: Optional[str] = None,
) -> bool:
    store = service.balance_holder_store
    if not store:
        service.last_error = "CRM недоступна — сегмент не сохранить"
        return False
    profile_key = normalize_inn(profile_inn)
    if not profile_key:
        service.last_error = "Неверный ИНН"
        return False
    ok = store.save_segment(profile_key, main_tab, housing_sub)
    if not ok:
        service.last_error = "Не удалось сохранить сегмент балансодержателя"
    return ok


def _is_candidate(company: DesignerAnalytics) -> bool:
    return is_visible_legal_status(company.legal_status) and company.nashdom_count > 0


def company_balance_segment(service, company: DesignerAnalytics) -> Tuple[Optional[str], Optional[str]]:
    store = service.balance_holder_store
    if not store:
        return None, None
    profile_key = normalize_inn(company.profile_key or company.inn) or company.inn
    return store.get_segment(profile_key, company.full_name, company.legal_form)
