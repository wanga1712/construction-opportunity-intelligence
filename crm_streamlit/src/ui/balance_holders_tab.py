"""Вкладка «Балансодержатели» с вложенными сегментами."""
from typing import Callable, List, Optional

import streamlit as st

from src.constants.balance_holder_registries import (
    BALANCE_HOLDER_LABELS,
    BALANCE_HOLDER_TABS,
    HOUSING_SUB_LABELS,
    HOUSING_SUB_TABS,
)
from src.services.companies_service import CompaniesService
from src.services.filters import filter_companies
from src.ui.balance_holder_card import render_balance_holder_card
from src.ui.card_pagination import render_card_grid_with_pagination


def _render_segment_list(
    service: CompaniesService,
    filtered: List,
    tab_key: str,
    page_size: int,
    segment_label: str,
    on_detail: Callable[[str], None],
    on_saved: Callable[[], None],
) -> None:
    st.caption(f"«{segment_label}» · отфильтровано: **{len(filtered)}**")
    if not filtered:
        st.info("Нет компаний по выбранным фильтрам.")
        return

    def _render(company) -> None:
        render_balance_holder_card(
            service,
            company,
            card_key=tab_key,
            on_detail=on_detail,
            on_saved=on_saved,
        )

    render_card_grid_with_pagination(filtered, tab_key, page_size, _render)


def render_balance_holders_tab(
    service: CompaniesService,
    search: str,
    region: Optional[str],
    page_size: int,
    on_detail: Callable[[str], None],
    on_saved: Callable[[], None],
) -> None:
    """Государственные / Коммерческие / Жилищные (+ подвкладки)."""
    unclassified = service.unclassified_balance_holders()
    if unclassified:
        st.caption(
            f"Без автосегмента: **{len(unclassified)}** "
            "(назначьте сегмент вручную — появятся в нужной вкладке)"
        )

    main_tabs = st.tabs([label for _, label in BALANCE_HOLDER_TABS])

    for idx, (main_code, main_label) in enumerate(BALANCE_HOLDER_TABS):
        with main_tabs[idx]:
            if main_code != "housing":
                base = service.companies_for_balance_holder(main_code)
                filtered = filter_companies(base, search=search, region=region)
                _render_segment_list(
                    service,
                    filtered,
                    tab_key=f"bh_{main_code}",
                    page_size=page_size,
                    segment_label=BALANCE_HOLDER_LABELS[main_code],
                    on_detail=on_detail,
                    on_saved=on_saved,
                )
                continue

            sub_tabs = st.tabs([label for _, label in HOUSING_SUB_TABS])
            for sub_idx, (sub_code, sub_label) in enumerate(HOUSING_SUB_TABS):
                with sub_tabs[sub_idx]:
                    base = service.companies_for_balance_holder("housing", sub_code)
                    filtered = filter_companies(base, search=search, region=region)
                    full_label = f"{BALANCE_HOLDER_LABELS['housing']} → {HOUSING_SUB_LABELS[sub_code]}"
                    _render_segment_list(
                        service,
                        filtered,
                        tab_key=f"bh_housing_{sub_code}",
                        page_size=page_size,
                        segment_label=full_label,
                        on_detail=on_detail,
                        on_saved=on_saved,
                    )
