"""OKPD funnel UI — paginated, lazy drilldown, one detail tree."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from src.services.v3_analytics_okpd import (
    SUBCATEGORY_NOT_ASSIGNED,
    SUBCATEGORY_NOT_ASSIGNED_LABEL_RU,
    display_cell,
    filter_okpd_rows,
)

INITIAL_OKPD_RENDER_LIMIT = 50
DEFAULT_PAGE_SIZE = 25
PAGE_SIZE_OPTIONS = (25, 50)
FILTER_BEFORE_RENDER = True
DRILLDOWN_EAGER_FOR_ALL_OKPD = False
DRILLDOWN_BUILD_ON_SELECTION = True
CATEGORY_TREE_LAZY = True
ONE_DETAIL_TREE_AT_A_TIME = True


def render_compact_kpis(data: Dict[str, Any]) -> None:
    cols = st.columns(6)
    specs = [
        ("Закупки S7", str(data.get("source_open") or 0)),
        ("Техн. допущено", str(data.get("target_v3_eligible_approx") or 0)),
        ("В CRM", str(data.get("crm_projected") or 0)),
        ("Routed", "— · NOT STARTED"),
        ("С возможностями", "— · NOT STARTED"),
        ("Candidate GOLD", "— · NOT STARTED"),
    ]
    if data.get("level_b_ready") and int(data.get("routed_procurements") or 0) > 0:
        specs[3] = ("Routed", str(data.get("routed_procurements") or 0))
        specs[4] = ("С возможностями", str(data.get("total_opportunities") or 0))
        g = data.get("candidate_gold")
        specs[5] = ("Candidate GOLD", str(g if g is not None else 0))
    for col, (title, val) in zip(cols, specs):
        with col:
            st.metric(title, val)


def prepare_okpd_page(
    rows: List[Dict[str, Any]],
    *,
    contour: str,
    okpd_q: str,
    category: str,
    page: int,
    page_size: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, int]:
    """Filter → sort → slice BEFORE any Streamlit widgets."""
    assert FILTER_BEFORE_RENDER is True
    filtered = filter_okpd_rows(rows, contour=contour, okpd_query=okpd_q, category_code=category)
    total = len(filtered)
    size = min(max(int(page_size), 1), INITIAL_OKPD_RENDER_LIMIT)
    pages = max(1, (total + size - 1) // size)
    page_i = min(max(int(page), 1), pages)
    start = (page_i - 1) * size
    page_rows = filtered[start : start + size]
    return filtered, page_rows, total, pages


def rows_to_table(page_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    table: List[Dict[str, Any]] = []
    for r in page_rows:
        priors = r.get("prepared_prior_categories") or []
        prior_txt = ", ".join(
            f"{p.get('display_name') or p.get('category_code')} [PREPARED PRIOR]"
            for p in priors[:6]
        ) or "—"
        table.append(
            {
                "OKPD": r.get("okpd_code"),
                "Наименование": (r.get("okpd_name") or "")[:70],
                "Получено": r.get("source_received", 0),
                "Техн. допущено": r.get("technically_eligible", 0),
                "Техн. искл.": r.get("technically_rejected", 0),
                "Neg.signal": display_cell(r.get("title_negative_signal")),
                "Hard excl.": display_cell(r.get("hard_excluded")),
                "В CRM": r.get("projected_to_crm", 0),
                "Pending routing": display_cell(r.get("pending_routing")),
                "Routed": display_cell(r.get("routed")),
                "Gold": display_cell(r.get("candidate_gold")),
                "Prepared priors": prior_txt,
            }
        )
    return table


def render_okpd_funnel_table(data: Dict[str, Any], *, contour: str, okpd_q: str, category: str) -> None:
    st.markdown("### Воронка по OKPD")
    funnel = data.get("okpd_funnel") or {}
    rows = funnel.get("rows") or []
    meta = funnel.get("meta") or {}

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        page_size = st.selectbox("Показывать", list(PAGE_SIZE_OPTIONS), index=0, key="v3_okpd_page_size")

    # Filter first (cheap) to bound page control max
    filtered_preview = filter_okpd_rows(rows, contour=contour, okpd_query=okpd_q, category_code=category)
    size = min(max(int(page_size), 1), INITIAL_OKPD_RENDER_LIMIT)
    pages_hint = max(1, (len(filtered_preview) + size - 1) // size)
    with c2:
        page = st.number_input(
            "Страница",
            min_value=1,
            max_value=pages_hint,
            value=min(int(st.session_state.get("v3_okpd_page") or 1), pages_hint),
            step=1,
            key="v3_okpd_page",
        )
    with c3:
        st.caption(f"стр. ≤{INITIAL_OKPD_RENDER_LIMIT} строк · без expanders на все OKPD")

    _, page_rows, total, pages = prepare_okpd_page(
        rows,
        contour=contour,
        okpd_q=okpd_q,
        category=category,
        page=int(page),
        page_size=int(page_size),
    )

    st.caption(
        f"Групп OKPD: **{meta.get('okpd_group_count', len(rows))}** · "
        f"после фильтра: **{total}** · на экране: **{len(page_rows)}** "
        f"(стр. {page}/{pages}, limit≤{INITIAL_OKPD_RENDER_LIMIT}) · "
        f"агрегация: **{meta.get('okpd_aggregation_duration_ms', '—')}** мс"
    )
    if not page_rows:
        st.info("Нет строк OKPD в снимке — нажмите «Обновить данные».")
        return

    assert len(page_rows) <= INITIAL_OKPD_RENDER_LIMIT
    table = rows_to_table(page_rows)
    st.dataframe(table, hide_index=True, use_container_width=True)

    # Single detail selection — only current page codes (not all 725)
    codes = [r.get("okpd_code") for r in page_rows if r.get("okpd_code")]
    selected = st.selectbox(
        "Детализация OKPD (одна строка)",
        ["—"] + codes,
        key="v3_okpd_detail",
    )
    if selected and selected != "—":
        row = next((r for r in page_rows if r.get("okpd_code") == selected), None)
        if row is not None:
            render_okpd_detail_panel(row, data)


def render_okpd_detail_panel(row: Dict[str, Any], data: Dict[str, Any]) -> None:
    """One detail tree at a time; category → subcategory lazy."""
    assert ONE_DETAIL_TREE_AT_A_TIME is True
    assert DRILLDOWN_BUILD_ON_SELECTION is True
    assert DRILLDOWN_EAGER_FOR_ALL_OKPD is False

    st.markdown(f"#### Детали: {row.get('okpd_code')}")
    st.write(f"**{row.get('okpd_code')}** · {row.get('okpd_name') or '—'}")
    st.write(
        f"44: **{row.get('source_44', 0)}** · 223: **{row.get('source_223', 0)}** · "
        f"WAITING: **{row.get('source_waiting', 0)}**"
    )
    st.write(
        f"Техн. допущено: **{row.get('technically_eligible', 0)}** · "
        f"искл.: **{row.get('technically_rejected', 0)}** "
        f"(MISSING_IDENTITY={row.get('reject_missing_identity', 0)})"
    )
    st.caption(
        f"Neg.signal: {display_cell(row.get('title_negative_signal'))} (soft≠DROP) · "
        f"Hard excl.: {display_cell(row.get('hard_excluded'))}"
    )

    priors = row.get("prepared_prior_categories") or []
    st.markdown("##### Prepared prior categories")
    if priors:
        st.dataframe(
            [
                {
                    "Категория": p.get("display_name"),
                    "code": p.get("category_code"),
                    "label": "PREPARED PRIOR",
                    "match": p.get("match_type"),
                }
                for p in priors
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.write("Нет prepared prior для этого OKPD.")

    # Lazy category selection
    assert CATEGORY_TREE_LAZY is True
    cat_options = ["—"] + [
        f"{p.get('display_name') or p.get('category_code')}|{p.get('category_code')}"
        for p in priors
    ]
    cat_sel = st.selectbox("Категория (lazy)", cat_options, key="v3_okpd_cat_sel")
    if not cat_sel or cat_sel == "—":
        st.caption("Выберите категорию, чтобы загрузить подкатегории.")
        return

    cat_code = cat_sel.split("|", 1)[-1]
    cat_name = cat_sel.split("|", 1)[0]
    st.write(f"Категория: **{cat_name}** · AI/routing: NOT STARTED")

    registry = data.get("subcategory_registry") or []
    sub_for_cat = [
        r for r in registry
        if r.get("category_code") == cat_code and r.get("subcategory_code")
    ]
    sub_options = ["—", f"{SUBCATEGORY_NOT_ASSIGNED_LABEL_RU}|{SUBCATEGORY_NOT_ASSIGNED}"]
    sub_options += [
        f"{r.get('subcategory_display_name') or r.get('subcategory_code')}|{r.get('subcategory_code')}"
        for r in sub_for_cat
    ]
    sub_sel = st.selectbox("Подкатегория (lazy)", sub_options, key="v3_okpd_sub_sel")
    if not sub_sel or sub_sel == "—":
        st.caption("Выберите подкатегорию для track/medal.")
        return

    sub_code = sub_sel.split("|", 1)[-1]
    sub_name = sub_sel.split("|", 1)[0]
    st.write(f"Подкатегория: **{sub_name}** (`{sub_code}`)")
    st.write(
        "Tracks / medals: Прямая поставка · В составе работ · "
        "Проектная потребность · Проектное влияние — **NOT STARTED**"
    )
    st.write("Confirmed medals — **NOT AVAILABLE** (documents).")
    st.caption("Список закупок: on-demand после routing (агрегаты только в снимке).")


def render_secondary_44_223(data: Dict[str, Any]) -> None:
    st.caption(
        f"44 OPEN **{data.get('source_44_open', 0)}** · WAITING **{data.get('source_44_waiting', 0)}** · "
        f"223 OPEN **{data.get('source_223_open', 0)}** · WAITING **{data.get('source_223_waiting', 0)}**"
    )


def render_categories_tab(data: Dict[str, Any], prepared: Dict[str, Any]) -> None:
    st.markdown("### Категории")
    coverage = prepared.get("category_coverage") or []
    registry = data.get("subcategory_registry") or []
    sub_count: Dict[str, int] = {}
    for r in registry:
        code = r.get("category_code")
        if code and r.get("subcategory_code"):
            sub_count[code] = sub_count.get(code, 0) + 1
    name_by = {
        r.get("category_code"): r.get("category_display_name")
        for r in registry
        if r.get("category_code") and r.get("category_display_name")
    }
    rows = []
    for c in coverage:
        code = c.get("category_code")
        rows.append(
            {
                "Категория": name_by.get(code, code),
                "code": code,
                "Подкатегорий": sub_count.get(code, 0),
                "OKPD priors": c.get("total_okpd_priors", 0),
                "Закупки": "— · NOT STARTED",
                "Gold": "— · NOT STARTED",
            }
        )
    st.dataframe(rows, hide_index=True, use_container_width=True)


def render_subcategories_tab(data: Dict[str, Any]) -> None:
    st.markdown("### Подкатегории")
    registry = data.get("subcategory_registry") or []
    rows = []
    for r in registry:
        if not r.get("subcategory_code"):
            continue
        rows.append(
            {
                "Категория": r.get("category_display_name") or r.get("category_code"),
                "Подкатегория": r.get("subcategory_display_name"),
                "code": r.get("subcategory_code"),
                "AI": "— · NOT STARTED",
            }
        )
    rows.append(
        {
            "Категория": "—",
            "Подкатегория": SUBCATEGORY_NOT_ASSIGNED_LABEL_RU,
            "code": SUBCATEGORY_NOT_ASSIGNED,
            "AI": "— · NOT STARTED",
        }
    )
    st.dataframe(rows, hide_index=True, use_container_width=True)


def render_scenarios_medals_quality(data: Dict[str, Any]) -> None:
    st.write("Сценарии / медали / качество — routing NOT STARTED, confirmed NOT AVAILABLE.")
    st.caption(f"OKPD priors runtime: {data.get('okpd_priors_status', 'NOT_DEPLOYED')}")
