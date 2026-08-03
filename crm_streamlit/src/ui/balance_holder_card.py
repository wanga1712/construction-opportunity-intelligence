"""Карточка балансодержателя: сегмент + компактные метрики."""
import html
from typing import Callable, Optional, Tuple

import streamlit as st

from modules.crm.analytics.analytics_models import DesignerAnalytics
from src.constants.balance_holder_registries import (
    BALANCE_HOLDER_LABELS,
    BALANCE_HOLDER_TABS,
    HOUSING_SUB_LABELS,
    HOUSING_SUB_TABS,
)
from src.services.companies_service import CompaniesService
from src.ui.company_title import format_company_display_name


def _stable_id(company: DesignerAnalytics) -> str:
    return company.profile_key or company.inn


def _main_options() -> Tuple[list, list]:
    labels = ["— не задан —"] + [label for _, label in BALANCE_HOLDER_TABS]
    codes: list = [None] + [code for code, _ in BALANCE_HOLDER_TABS]
    return labels, codes


def _housing_options() -> Tuple[list, list]:
    labels = ["— не задан —"] + [label for _, label in HOUSING_SUB_TABS]
    codes: list = [None] + [code for code, _ in HOUSING_SUB_TABS]
    return labels, codes


def render_balance_holder_card(
    service: CompaniesService,
    company: DesignerAnalytics,
    card_key: str,
    on_detail: Callable[[str], None],
    on_saved: Callable[[], None],
) -> None:
    """Карточка с выбором сегмента балансодержателя."""
    store = service.balance_holder_store
    readonly = store is None
    stable = _stable_id(company)
    profile_inn = stable

    main_tab, housing_sub = store.get_segment(
        profile_inn, company.full_name, company.legal_form,
    ) if store else (None, None)

    main_labels, main_codes = _main_options()
    housing_labels, housing_codes = _housing_options()
    main_idx = main_codes.index(main_tab) if main_tab in main_codes else 0
    housing_idx = housing_codes.index(housing_sub) if housing_sub in housing_codes else 0

    title = format_company_display_name(company.full_name, company.legal_form)

    with st.container(border=True):
        head_l, head_r = st.columns([0.78, 0.22])
        with head_l:
            st.markdown(
                f'<p class="crm-card-name">{html.escape(title)}</p>',
                unsafe_allow_html=True,
            )
            st.caption(f"ИНН {company.inn} · {company.region} · NashDom {company.nashdom_count}")
        with head_r:
            if st.button(
                "Подробнее",
                key=f"bh_detail_{card_key}_{stable}",
                type="primary",
                use_container_width=True,
            ):
                on_detail(company.inn)

        if readonly:
            seg = BALANCE_HOLDER_LABELS.get(main_tab or "", "—")
            if main_tab == "housing" and housing_sub:
                seg += f" / {HOUSING_SUB_LABELS.get(housing_sub, housing_sub)}"
            st.caption(f"Сегмент: {seg}")
            return

        with st.form(key=f"bh_form_{card_key}_{stable}", clear_on_submit=False):
            c1, c2, c3 = st.columns([1.2, 1.2, 0.25])
            with c1:
                main_sel = st.selectbox(
                    "Сегмент",
                    options=main_labels,
                    index=main_idx,
                    label_visibility="collapsed",
                )
            main_code_sel = main_codes[main_labels.index(main_sel)]
            with c2:
                housing_sel = st.selectbox(
                    "Подтип жилищных",
                    options=housing_labels,
                    index=housing_idx,
                    disabled=main_code_sel != "housing",
                    label_visibility="collapsed",
                )
            with c3:
                submitted = st.form_submit_button("💾", help="Сохранить сегмент")

        if submitted and store:
            new_main = main_codes[main_labels.index(main_sel)]
            new_housing = None
            if new_main == "housing":
                new_housing = housing_codes[housing_labels.index(housing_sel)]
            if service.save_balance_holder_segment(profile_inn, new_main, new_housing):
                st.toast("Сегмент сохранён", icon="✅")
                on_saved()
            else:
                st.error(service.last_error or "Не удалось сохранить сегмент")
