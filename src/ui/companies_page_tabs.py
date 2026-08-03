"""Registry tabs and card grids for the companies page."""
from typing import Callable

import streamlit as st

from modules.crm.analytics.designer_profile_constants import REGISTRIES, REGISTRY_LABELS
from src.services.companies_service import CompaniesService
from src.services.filters import filter_companies
from src.ui.balance_holders_tab import render_balance_holders_tab
from src.ui.card_pagination import render_card_grid_with_pagination
from src.ui.company_card import render_company_card


def _base_list(service: CompaniesService, registry_key: str, favorites_tab: bool) -> list:
    if favorites_tab:
        return service.favorite_companies()
    base = service.companies_for_registry(registry_key)
    if st.session_state.get("favorites_only"):
        base = [company for company in base if company.is_favorite]
    return base


def _render_registry_cards(
    service: CompaniesService,
    filtered: list,
    tab_key: str,
    page_size: int,
    on_detail: Callable[[str], None],
    on_saved: Callable[[], None],
) -> None:
    def render_card(company) -> None:
        render_company_card(
            service, company, card_key=tab_key, on_detail=on_detail, on_saved=on_saved,
        )

    render_card_grid_with_pagination(filtered, tab_key, page_size, render_card)


def render_company_tabs(
    service: CompaniesService,
    search: str,
    region: str | None,
    grade: str | None,
    page_size: int,
    on_detail: Callable[[str], None],
    on_saved: Callable[[], None],
) -> None:
    tab_labels = [label for _, label in REGISTRIES]
    tab_labels += ["Балансодержатели", f"⭐ Избранные ({len(service.favorite_companies())})"]
    tabs = st.tabs(tab_labels)
    registry_keys = [key for key, _ in REGISTRIES]
    balance_tab_idx = len(registry_keys)
    favorites_tab_idx = balance_tab_idx + 1

    for idx, tab in enumerate(tabs):
        with tab:
            if idx == balance_tab_idx:
                render_balance_holders_tab(
                    service, search=search, region=region, page_size=page_size,
                    on_detail=on_detail, on_saved=on_saved,
                )
                continue
            favorites_tab = idx == favorites_tab_idx
            registry_key = registry_keys[idx] if not favorites_tab else ""
            filtered = filter_companies(
                _base_list(service, registry_key, favorites_tab),
                search=search, region=region, grade=grade,
            )
            reg_name = REGISTRY_LABELS.get(registry_key, "Избранные")
            st.caption(f"Реестр «{reg_name}» · отфильтровано: **{len(filtered)}**")
            if not filtered:
                st.info("Нет компаний по выбранным фильтрам.")
                continue
            _render_registry_cards(
                service, filtered, tab_key=f"tab_{idx}", page_size=page_size,
                on_detail=on_detail, on_saved=on_saved,
            )
