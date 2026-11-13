"""Three-zone commercial market and anchored dossier workspace."""
from __future__ import annotations

import time
from typing import Any

import streamlit as st

from src.services.commercial_market_read_model import (
    KIND_LABELS,
    MATCHED,
    NO_ESTIMATE,
    SYSTEM_STATES,
    ZERO_MATCH,
    load_filter_options,
    load_market_cards,
)
from src.services.procurement_card_dossier_service import load_procurement_dossier
from src.ui.components.commercial_market.cards import render_market_cards
from src.ui.components.commercial_market.dossier import DOSSIER_TABS, render_dossier
from src.ui.components.commercial_market.loading import (
    CommercialLoadingState,
    LOADING_IMAGES,
    LOADING_PHRASES,
)
from src.ui.components.commercial_market.styles import MARKET_CSS


def _query_default(key: str, state_key: str) -> None:
    value = st.query_params.get(key)
    if value and state_key not in st.session_state:
        st.session_state[state_key] = value


def _header(counts: dict | None = None) -> None:
    counts = counts or {}
    count_line = ""
    if counts:
        count_line = (
            f"MATCHED {int(counts.get('matched') or 0)} · ZERO MATCH {int(counts.get('zero_match') or 0)}<br>"
            f"IN RESEARCH {int(counts.get('in_research') or 0)} · "
            f"NO ESTIMATE {int(counts.get('no_estimate') or 0)}"
        )
    st.markdown(
        f"""
        <div class="crm-market-top">
          <div class="crm-market-brand">Коммерческое досье
            <small>CONSTRUCTION OPPORTUNITY INTELLIGENCE · MARKET WORKSPACE</small>
          </div>
          <div class="crm-market-count">
            {count_line}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _left_filters(options: dict, counts: dict) -> dict:
    st.markdown('<div class="crm-zone-title">Мои категории</div>', unsafe_allow_html=True)
    category_options = {
        str(row.get("category_code")): f"{row.get('category_name') or row.get('category_code')} · {int(row.get('n') or 0)}"
        for row in options.get("categories") or []
        if row.get("category_code")
    }
    category_codes = st.multiselect(
        "Категории",
        options=list(category_options),
        format_func=lambda key: category_options.get(key, key),
        placeholder="Все категории",
        key="market_categories",
        label_visibility="collapsed",
    )

    st.markdown('<div class="crm-filter-label">Регион</div>', unsafe_allow_html=True)
    regions = ["Все регионы"] + [
        str(row.get("name")) for row in options.get("regions") or [] if row.get("name")
    ]
    region = st.selectbox("Регион", regions, key="market_region", label_visibility="collapsed")

    st.markdown('<div class="crm-filter-label">Статус закупки</div>', unsafe_allow_html=True)
    stage = st.selectbox(
        "Статус закупки",
        ["Все статусы", "Идут торги", "Комиссия", "Разыгранные"],
        key="market_stage",
        label_visibility="collapsed",
    )
    stage_value = {
        "Все статусы": None,
        "Идут торги": "torgi",
        "Комиссия": "commission",
        "Разыгранные": "razygranye",
    }[stage]

    st.markdown('<div class="crm-filter-label">Lifecycle</div>', unsafe_allow_html=True)
    lifecycle_label = st.selectbox(
        "Lifecycle",
        ["Все lifecycle", "OPEN", "AWARDED"],
        key="market_lifecycle",
        label_visibility="collapsed",
    )

    st.markdown('<div class="crm-filter-label">Минимальная сумма</div>', unsafe_allow_html=True)
    min_amount = st.number_input(
        "Минимальная сумма",
        min_value=0,
        value=0,
        step=500_000,
        format="%d",
        key="market_min_amount",
        label_visibility="collapsed",
    )

    st.markdown('<div class="crm-filter-label">Медаль</div>', unsafe_allow_html=True)
    medal = st.selectbox(
        "Медаль",
        ["Любая", "GOLD", "SILVER", "BRONZE", "WOOD"],
        key="market_medal",
        label_visibility="collapsed",
    )

    st.markdown('<div class="crm-filter-label">Состояния системы</div>', unsafe_allow_html=True)
    state_labels = {"Все состояния": None, **{KIND_LABELS[s]: s for s in SYSTEM_STATES}}
    state_label = st.radio(
        "Состояния системы",
        list(state_labels),
        key="market_state",
        label_visibility="collapsed",
    )
    st.markdown(
        f"""
        <div class="crm-system-list">
          <div class="crm-system-row"><span>MATCHED</span><b>есть совпадения</b></div>
          <div class="crm-system-row"><span>ZERO_MATCH</span><b>полная смета без совпадений</b></div>
          <div class="crm-system-row"><span>IN_RESEARCH</span><b>идёт обработка</b></div>
          <div class="crm-system-row"><span>NO_ESTIMATE</span><b>смета ещё не готова</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return {
        "category_codes": category_codes,
        "region": None if region == "Все регионы" else region,
        "lifecycle": None if lifecycle_label == "Все lifecycle" else lifecycle_label,
        "stage": stage_value,
        "min_amount": float(min_amount or 0),
        "medal": None if medal == "Любая" else medal,
        "system_state": state_labels[state_label],
    }


def _selected_pid(cards: list[dict]) -> int | None:
    available = {int(card["procurement_id"]) for card in cards}
    session_pid = st.session_state.get("market_selected_pid")
    try:
        selected = int(session_pid) if session_pid is not None else None
    except (TypeError, ValueError):
        selected = None
    if selected in available:
        return selected
    raw = st.query_params.get("market_pid")
    try:
        selected = int(raw) if raw else None
    except (TypeError, ValueError):
        selected = None
    if selected in available:
        st.session_state.market_selected_pid = selected
        return selected
    matched = next((card for card in cards if card["state"] == MATCHED), None)
    if matched:
        return int(matched["procurement_id"])
    return int(cards[0]["procurement_id"]) if cards else None


def _render_loader_demo() -> None:
    if not st.query_params.get("loader_demo") or st.session_state.get("market_loader_demo_done"):
        return
    with CommercialLoadingState(LOADING_PHRASES[2], image=LOADING_IMAGES[2]):
        time.sleep(2.0)
    st.session_state.market_loader_demo_done = True


def render_commercial_market_page(service: Any) -> None:
    crm_db = getattr(service, "crm_db", None) if service is not None else None
    if crm_db is None:
        from src.services.db_bootstrap import connect_databases

        _radar, _tender, crm_db, _warn = connect_databases()
    st.markdown(MARKET_CSS, unsafe_allow_html=True)
    _render_loader_demo()
    _query_default("market_q", "market_search")

    options = load_filter_options(crm_db)
    _header()
    search = st.text_input(
        "Поиск по закупкам, сметам и материалам",
        placeholder="Поиск по закупкам, сметам и материалам",
        key="market_search",
        label_visibility="collapsed",
    )

    left, center, right = st.columns([0.95, 2.2, 2.65], gap="small")
    with left:
        with st.container(key="market_left"):
            filters = _left_filters(options, st.session_state.get("market_last_counts") or {})

    with center:
        with st.container(key="market_list"):
            st.markdown('<div class="crm-zone-title">Мои объекты</div>', unsafe_allow_html=True)
            slot = st.empty()
            with CommercialLoadingState(
                LOADING_PHRASES[0],
                image=LOADING_IMAGES[0],
                slot=slot,
            ):
                result = load_market_cards(
                    crm_db,
                    search_text=search or "",
                    category_codes=filters["category_codes"],
                    region=filters["region"],
                    lifecycle=filters["lifecycle"],
                    stage=filters["stage"],
                    min_amount=filters["min_amount"],
                    system_state=filters["system_state"],
                    medal=filters["medal"],
                    limit=80,
                )
            st.session_state.market_last_counts = result
            cards = result.get("cards") or []
            selected_pid = _selected_pid(cards)
            st.markdown(
                f"""
                <div class="crm-market-count" style="text-align:left;margin-bottom:8px">
                  MATCHED {int(result.get("matched") or 0)} · ZERO MATCH {int(result.get("zero_match") or 0)}
                  · IN RESEARCH {int(result.get("in_research") or 0)}
                  · NO ESTIMATE {int(result.get("no_estimate") or 0)}
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(
                f"Объектов: {len(cards)}"
                + (f" · поиск: {search}" if search else "")
                + " · карточки сгруппированы по закупке"
            )
            chosen_pid = render_market_cards(cards, selected_pid=selected_pid)
            if chosen_pid is not None:
                st.session_state.market_selected_pid = chosen_pid
                st.query_params["market_pid"] = str(chosen_pid)
                st.rerun()

    with right:
        with st.container(key="market_right"):
            st.markdown('<div class="crm-zone-title">Dossier</div>', unsafe_allow_html=True)
            selected_card = next(
                (card for card in cards if int(card["procurement_id"]) == selected_pid),
                None,
            )
            if selected_pid is None:
                st.markdown(
                    '<div class="crm-panel-card dark">Выберите объект в центральной колонке, '
                    'чтобы открыть коммерческое досье.</div>',
                    unsafe_allow_html=True,
                )
            else:
                if st.query_params.get("market_tab"):
                    st.session_state[f"market_dossier_tab_{selected_pid}"] = st.query_params["market_tab"]
                with CommercialLoadingState(
                    LOADING_PHRASES[1],
                    image=LOADING_IMAGES[1],
                ):
                    dossier = load_procurement_dossier(crm_db, selected_pid)
                render_dossier(dossier, crm_db, card=selected_card)
