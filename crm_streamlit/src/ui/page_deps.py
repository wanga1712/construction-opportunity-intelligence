"""Page dependency contract for CRM Streamlit routing.

Lightweight pages must not initialize CompaniesService / Radar designer loads.
"""
from __future__ import annotations

from enum import Enum


class PageDependency(str, Enum):
    NO_SERVICE = "NO_SERVICE"
    CRM_DB_ONLY = "CRM_DB_ONLY"
    COMPANIES_SERVICE = "COMPANIES_SERVICE"
    OTHER = "OTHER"


# Sidebar + hidden routes. Default for unknown keys: COMPANIES_SERVICE.
PAGE_DEPENDENCY: dict[str, PageDependency] = {
    # Heavy analytics / contour (need CompaniesService + Radar designers)
    "objects_v2": PageDependency.COMPANIES_SERVICE,
    "objects": PageDependency.COMPANIES_SERVICE,
    "objects_copy": PageDependency.COMPANIES_SERVICE,
    "analytics_v3": PageDependency.COMPANIES_SERVICE,
    "opportunity_radar": PageDependency.COMPANIES_SERVICE,
    "computers": PageDependency.COMPANIES_SERVICE,
    "waterproofing": PageDependency.COMPANIES_SERVICE,
    "map": PageDependency.COMPANIES_SERVICE,
    "ai_review": PageDependency.COMPANIES_SERVICE,
    "companies": PageDependency.COMPANIES_SERVICE,
    "export_pdf": PageDependency.COMPANIES_SERVICE,
    # Tender DB alerts/queues — needs DB handles, not designer load_sync
    "infrastructure": PageDependency.OTHER,
    # Snapshot-only / local CRM config — no CompaniesService
    "system_health": PageDependency.NO_SERVICE,
    "crm_profiles": PageDependency.NO_SERVICE,
    # Parking DB via session_deps — not CompaniesService
    "customers": PageDependency.NO_SERVICE,
    # Registry editor uses CRM DB only
    "category_registry": PageDependency.CRM_DB_ONLY,
}

LIGHTWEIGHT_NO_COMPANIES = frozenset(
    {
        key
        for key, dep in PAGE_DEPENDENCY.items()
        if dep in (PageDependency.NO_SERVICE, PageDependency.OTHER, PageDependency.CRM_DB_ONLY)
    }
)


def page_dependency(page: str) -> PageDependency:
    return PAGE_DEPENDENCY.get(page, PageDependency.COMPANIES_SERVICE)


def requires_companies_service(page: str) -> bool:
    return page_dependency(page) == PageDependency.COMPANIES_SERVICE


def requires_companies_load_sync(page: str) -> bool:
    """True only when Radar designer contour must be loaded."""
    return page_dependency(page) == PageDependency.COMPANIES_SERVICE
