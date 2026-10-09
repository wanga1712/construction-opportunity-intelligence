"""Страница аналитического контура v2 (§14.1–14.3)."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.control_room_links import apply_control_room_links

_STICKY_CSS = """
<style>
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {
    position: -webkit-sticky;
    position: sticky;
    top: 3rem;
    max-height: calc(100vh - 4rem);
    overflow-y: auto;
    align-self: flex-start;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child::-webkit-scrollbar {
    width: 4px;
}
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child::-webkit-scrollbar-thumb {
    background: #ccc;
    border-radius: 2px;
}
</style>
"""


def render_analytics_contour_v2_page(service) -> None:
    """Первый экран — реальная коммерческая очередь «Очередь возможностей».

    Тяжёлая аналитика (KPI, графики, lifecycle worksets, иерархия категорий,
    документы, AI payload) живёт за явным открытием в конце ленты.
    """
    # URL-навигация панели управления (?cr_cat / ?cr_open) на рабочую область.
    apply_control_room_links()

    from src.ui.queue_first_page import render_queue_first_page

    render_queue_first_page(service)


def _analytics_crm_db(service):
    """Return a CRM database handle without changing page/dependency wiring."""
    crm_db = getattr(service, "crm_db", None) if service is not None else None
    if crm_db is not None:
        return crm_db
    from src.services.db_bootstrap import connect_databases

    _radar, _tender, crm_db, _warn = connect_databases()
    return crm_db


def _load_category_overview(crm_db):
    from src.services.category_overview_service import get_category_overview

    if crm_db is None:
        return {"categories": []}
    try:
        return get_category_overview(crm_db)
    except Exception as exc:
        st.error(f"Не удалось загрузить товарные категории: {exc}")
        return {"categories": []}


def _load_category_summary(crm_db, medal_view):
    from src.services.category_overview_service import get_category_summary

    if crm_db is None:
        return {
            "category_count": 0,
            "opportunity_count": 0,
            "total_amount": 0,
            "medals": {"gold": 0, "silver": 0, "bronze": 0, "wood": 0},
        }
    try:
        return get_category_summary(crm_db, medal_view=medal_view)
    except Exception as exc:
        st.error(f"Не удалось загрузить сводку: {exc}")
        return {
            "category_count": 0,
            "opportunity_count": 0,
            "total_amount": 0,
            "medals": {"gold": 0, "silver": 0, "bronze": 0, "wood": 0},
        }


def _format_amount(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f} млн ₽"
    if number >= 1_000:
        return f"{number / 1_000:.1f} тыс ₽"
    return f"{number:,.0f} ₽"


def _medal_counts(category, medal_view):
    if medal_view == "initial":
        return category.get("initial_medals") or {
            "gold": 0,
            "silver": 0,
            "bronze": 0,
            "wood": 0,
        }
    return category.get("current_medals") or {
        "gold": 0,
        "silver": 0,
        "bronze": 0,
        "wood": 0,
    }


def _render_summary(summary) -> None:
    medals = summary.get("medals") or {}
    columns = st.columns(7)
    columns[0].metric("Категорий", summary.get("category_count", 0))
    columns[1].metric("Возможностей", summary.get("opportunity_count", 0))
    columns[2].metric("Сумма закупок", _format_amount(summary.get("total_amount", 0)))
    columns[3].metric("🥇 Gold", medals.get("gold", 0))
    columns[4].metric("🥈 Silver", medals.get("silver", 0))
    columns[5].metric("🥉 Bronze", medals.get("bronze", 0))
    columns[6].metric("🪵 Wood", medals.get("wood", 0))


def _render_category_cards(categories, medal_view) -> None:
    if not categories:
        st.info("Активные товарные категории пока не найдены.")
        return
    for category in categories:
        medals = _medal_counts(category, medal_view)
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.markdown(
                    f"### {category.get('category_name') or category.get('category_code')}"
                )
                st.caption(
                    f"{category.get('procurement_count', 0)} закупок · "
                    f"{_format_amount(category.get('total_amount', 0))} · "
                    f"прямая поставка {category.get('direct_supply_count', 0)} · "
                    f"в составе работ {category.get('works_with_products_count', 0)}"
                )
                st.caption(
                    "Медали: "
                    f"Gold {medals.get('gold', 0)} · "
                    f"Silver {medals.get('silver', 0)} · "
                    f"Bronze {medals.get('bronze', 0)} · "
                    f"Wood {medals.get('wood', 0)}"
                )
            with right:
                if st.button(
                    "Открыть",
                    key=f"category_open_{category.get('category_code')}",
                    use_container_width=True,
                ):
                    st.session_state["analytics_category_code"] = category.get(
                        "category_code"
                    )
                    st.rerun()


def _document_category_value(row):
    """Confirmed DOCUMENT category value only; never falls back to НМЦК."""
    basis = str(row.get("category_value_basis") or "").strip().upper()
    val = row.get("expected_category_value")
    if val is None or not basis.startswith("DOCUMENT_"):
        return None
    return val


def _fmt_doc_category_value(row):
    v = _document_category_value(row)
    return _format_amount(v) if v is not None else "—"


def _render_category_detail(crm_db, categories, category_code, medal_view) -> None:
    category = next(
        (item for item in categories if item.get("category_code") == category_code),
        None,
    )
    if category is None:
        st.warning("Категория не найдена.")
        return

    top_left, top_right = st.columns([5, 1])
    with top_right:
        if st.button("← К категориям", key="category_back", use_container_width=True):
            st.session_state["analytics_category_code"] = None
            st.session_state["analytics_subcategory_code"] = None
            st.rerun()

    with top_left:
        st.markdown(f"## {category.get('category_name')}")

    subcategories = category.get("subcategories") or []
    unclassified = category.get("unclassified") or {
        "procurement_count": 0,
        "total_amount": 0,
    }
    selected_subcategory = st.session_state.get("analytics_subcategory_code")

    if selected_subcategory is None:
        st.subheader("Подкатегории")
        for sub in subcategories:
            label = sub.get("subcategory_name") or sub.get("subcategory_code")
            cols = st.columns([4, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{label}**")
            with cols[1]:
                st.caption(f"{sub.get('procurement_count', 0)} закупок")
            with cols[2]:
                st.caption(_format_amount(sub.get("total_amount", 0)))
            with cols[3]:
                if st.button(
                    "Открыть",
                    key=f"subcat_open_{sub.get('subcategory_code')}",
                    use_container_width=True,
                ):
                    st.session_state["analytics_subcategory_code"] = sub.get(
                        "subcategory_code"
                    )
                    st.rerun()

        if unclassified.get("procurement_count") or unclassified.get("total_amount"):
            cols = st.columns([4, 1, 1, 1])
            with cols[0]:
                st.markdown("**Не классифицировано**")
            with cols[1]:
                st.caption(f"{unclassified.get('procurement_count', 0)} закупок")
            with cols[2]:
                st.caption(_format_amount(unclassified.get("total_amount", 0)))
            with cols[3]:
                if st.button(
                    "Открыть",
                    key="subcat_open_unclassified",
                    use_container_width=True,
                ):
                    st.session_state["analytics_subcategory_code"] = "__unclassified__"
                    st.rerun()
        return

    sub_info = next(
        (sub for sub in subcategories if sub.get("subcategory_code") == selected_subcategory),
        None,
    )
    if selected_subcategory == "__unclassified__":
        sub_label = "Не классифицировано"
        sub_count = unclassified.get("procurement_count", 0)
        sub_amount = unclassified.get("total_amount", 0)
    else:
        sub_label = (sub_info or {}).get("subcategory_name") or selected_subcategory
        sub_count = (sub_info or {}).get("procurement_count", 0)
        sub_amount = (sub_info or {}).get("total_amount", 0)

    if st.button("← Все подкатегории", key="subcategory_back", use_container_width=True):
        st.session_state["analytics_subcategory_code"] = None
        st.rerun()

    st.markdown(
        f"Все категории → {category.get('category_name')} → {sub_label}"
    )
    st.metric("Закупок", sub_count)
    _amt1, _amt2 = st.columns(2)
    _amt1.metric("НМЦК закупок", _format_amount(sub_amount))
    _amt2.metric("Подтверждено по проектной документации", "—")

    try:
        from src.services.category_overview_service import get_category_procurements

        procurements = get_category_procurements(
            crm_db, category_code, selected_subcategory
        )
    except Exception as exc:
        st.error(f"Не удалось загрузить закупки: {exc}")
        procurements = []

    if procurements:
        st.dataframe(
            [
                {
                    "Закупка": row.get("auction_name"),
                    "Подкатегория": row.get("subcategory_name"),
                    "Товар": row.get("product_name"),
                    "Кол-во": row.get("quantity"),
                    "Ед.": row.get("unit"),
                    "НМЦК закупки": _format_amount(row.get("initial_price")),
                    "Подтверждено по проектной документации": _fmt_doc_category_value(row),
                    "Режим": row.get("procurement_mode"),
                    "Объект": row.get("object_type"),
                    "Работы": row.get("work_type"),
                    "Первичная медаль": row.get("candidate_initial_medal"),
                    "Текущая медаль": row.get("current_effective_medal"),
                }
                for row in procurements
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("Закупки по подкатегории не найдены.")


def render_analytics_contour_v2_page(service) -> None:
    """Category-first start screen for the analytics contour."""
    crm_db = _analytics_crm_db(service)
    overview = _load_category_overview(crm_db)
    categories = overview.get("categories") or []

    st.title("Аналитический контур")
    st.caption("Товарные категории и коммерческие возможности")

    view_label = st.segmented_control(
        "Показатель",
        ["Первичные", "Текущие"],
        default="Первичные",
        key="analytics_medal_view",
    )
    medal_view = "initial" if view_label != "Текущие" else "current"

    selected_category = st.session_state.get("analytics_category_code")
    if selected_category:
        _render_category_detail(crm_db, categories, selected_category, medal_view)
        return

    summary = _load_category_summary(crm_db, medal_view)
    _render_summary(summary)
    st.divider()
    _render_category_cards(categories, medal_view)


def _render_technical_diagnostics() -> None:
    """Служебная диагностика: heartbeat очереди и состояние контура."""
    from src.ui.components.analytics_v2.control_room import render_control_room

    render_control_room()


def _render_filters() -> None:
    """Панель фильтров — левая колонка, динамические данные из БД."""
    from src.services.crm_profile_service import (
        load_profiles,
        load_profile_counts,
        load_category_hierarchy,
    )

    st.markdown("**ФИЛЬТРЫ**")

    # --- Профиль ---
    profiles = load_profiles()
    profile_counts = load_profile_counts()
    total_active = sum(profile_counts.values())
    profile_options = [{"id": None, "name": "Все профили"}] + profiles

    def _fmt_profile(pid):
        if pid is None:
            return f"Все профили ({total_active})"
        p = next((x for x in profiles if x["id"] == pid), None)
        if not p:
            return "—"
        cnt = profile_counts.get(pid, 0)
        return f"{p['name']} ({cnt})" if cnt else p["name"]

    selected_profile = st.selectbox(
        "Профиль",
        options=[p["id"] for p in profile_options],
        format_func=_fmt_profile,
        key="analytics_v2_profile_filter",
    )

    # --- Уровень ---
    st.segmented_control(
        "Уровень",
        ["Все", "Gold", "Silver", "Bronze"],
        default="Все",
        selection_mode="single",
        key="analytics_v2_level_filter",
    )

    # --- Регион ---
    db_regions = _load_regions_from_db()
    selected_region = st.selectbox(
        "Регион",
        ["Все регионы"] + db_regions,
        index=0,
        key="analytics_v2_region_filter",
    )

    # --- Иерархический фильтр категорий ---
    filters_for_counts: dict = {}
    if selected_profile:
        filters_for_counts["profile_id"] = selected_profile
    if selected_region and selected_region != "Все регионы":
        filters_for_counts["region"] = selected_region

    _render_category_filter_panel(filters_for_counts)

    st.selectbox("Тип объекта", ["Все", "Социальный", "Инфраструктурный", "Жилой"], index=0)
    st.selectbox("Заказчик", ["Все"], index=0)

    st.radio(
        "Показывать",
        ["Все", "Новые", "Обновлённые", "Сохранённые"],
        index=0,
        key="analytics_v2_show_mode",
    )

    st.button("Расширенные фильтры", use_container_width=True)
    if st.button("Сбросить фильтры", use_container_width=True):
        _reset_analytics_filters_state(st.session_state)
        st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Иерархический фильтр категорий (CRM-FILTER-1)
# ──────────────────────────────────────────────────────────────────────────────

_STAGE_LABELS: dict[str, str] = {
    "torgi": "Торги",
    "commission": "Комиссия",
    "razygranye": "Разыгранные",
}
_STAGES = list(_STAGE_LABELS.keys())


def _cat_sess_key(stage: str) -> str:
    return f"_catf_{stage}_cats"


def _subcat_sess_key(stage: str) -> str:
    return f"_catf_{stage}_subs"


def _stage_sess_key() -> str:
    return "analytics_v2_cat_stage"


def _init_cat_state(stage: str, hierarchy: dict) -> None:
    """Инициализирует session state для стадии если ещё не установлен."""
    ck = _cat_sess_key(stage)
    sk = _subcat_sess_key(stage)
    if ck not in st.session_state:
        st.session_state[ck] = set(hierarchy.keys())
    if sk not in st.session_state:
        st.session_state[sk] = {
            cat: set(info["subcategories"].keys())
            for cat, info in hierarchy.items()
        }
    st.session_state.setdefault(f"_catf_{stage}_explicit", False)


def _reset_all_category_filters(session: dict | None = None) -> None:
    """Удаляет все category filter ключи из session_state."""
    session = session if session is not None else st.session_state
    for stage in _STAGES:
        for k in [_cat_sess_key(stage), _subcat_sess_key(stage), f"_catf_{stage}_explicit"]:
            session.pop(k, None)
    session.pop(_stage_sess_key(), None)


def _reset_analytics_filters_state(session: dict) -> None:
    """Restore list mode and filter defaults without touching unrelated state."""
    _reset_all_category_filters(session)
    for key in (
        "analytics_v2_profile_filter",
        "analytics_v2_level_filter",
        "analytics_v2_region_filter",
        "analytics_v2_show_mode",
        "selected_torgi_id",
        "_cr_scope_ids",
        "_cr_scope_label",
        "selected_komissia_id",
        "selected_razygr_id",
        "annotation_active_queue_session_key",
        "annotation_go_next",
        "annotation_go_next_from",
    ):
        session.pop(key, None)


def _render_category_filter_panel(filters_for_counts: dict) -> None:
    """Иерархический фильтр категорий через st.expander с чекбоксами."""
    from src.services.crm_profile_service import load_category_hierarchy

    # Выбор стадии для подсчёта
    active_stage = st.session_state.get(_stage_sess_key(), "torgi")
    if active_stage not in _STAGES:
        active_stage = "torgi"

    # Небольшой селектор стадии
    stage_choice = st.radio(
        "Категории для:",
        options=_STAGES,
        format_func=lambda s: _STAGE_LABELS[s],
        index=_STAGES.index(active_stage),
        horizontal=True,
        key="analytics_v2_cat_stage_radio",
        label_visibility="collapsed",
    )
    if stage_choice != active_stage:
        st.session_state[_stage_sess_key()] = stage_choice
        active_stage = stage_choice

    hierarchy = load_category_hierarchy(active_stage, filters_for_counts or None)

    _init_cat_state(active_stage, hierarchy)
    selected_cats: set = st.session_state[_cat_sess_key(active_stage)]
    all_cats = set(hierarchy.keys())

    total_count = sum(info["count"] for info in hierarchy.values())
    all_selected = bool(all_cats) and selected_cats >= all_cats

    with st.expander(f"Категория ▸  ({len(selected_cats)}/{len(all_cats)})", expanded=False):
        # --- Кнопки управления ---
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Выбрать всё", key=f"_catf_{active_stage}_btn_all",
                         use_container_width=True):
                st.session_state[_cat_sess_key(active_stage)] = set(hierarchy.keys())
                st.session_state[_subcat_sess_key(active_stage)] = {
                    cat: set(info["subcategories"].keys())
                    for cat, info in hierarchy.items()
                }
                st.session_state[f"_catf_{active_stage}_explicit"] = False
                st.rerun()
        with b2:
            if st.button("Снять всё", key=f"_catf_{active_stage}_btn_none",
                         use_container_width=True):
                st.session_state[_cat_sess_key(active_stage)] = set()
                st.session_state[_subcat_sess_key(active_stage)] = {
                    cat: set() for cat in hierarchy
                }
                st.session_state[f"_catf_{active_stage}_explicit"] = True
                st.rerun()

        if st.button("Только подтверждённые", key=f"_catf_{active_stage}_btn_conf",
                     use_container_width=True):
            # Категории с подкатегориями (= есть записи из crm_category_candidates)
            confirmed = {
                cat for cat, info in hierarchy.items()
                if info["subcategories"] and cat != "uncategorized"
            }
            if not confirmed:
                confirmed = {c for c in all_cats if c != "uncategorized"}
            st.session_state[_cat_sess_key(active_stage)] = confirmed
            st.session_state[_subcat_sess_key(active_stage)] = {
                cat: set(info["subcategories"].keys())
                for cat, info in hierarchy.items()
                if cat in confirmed
            }
            st.session_state[f"_catf_{active_stage}_explicit"] = True
            st.rerun()

        st.markdown("---")

        # --- Мастер-чекбокс «Все категории» ---
        def _on_master() -> None:
            val = st.session_state[f"_catcb_{active_stage}_all"]
            new_cats = set(hierarchy.keys()) if val else set()
            new_subs = (
                {cat: set(info["subcategories"].keys()) for cat, info in hierarchy.items()}
                if val
                else {cat: set() for cat in hierarchy}
            )
            st.session_state[_cat_sess_key(active_stage)] = new_cats
            st.session_state[_subcat_sess_key(active_stage)] = new_subs
            st.session_state[f"_catf_{active_stage}_explicit"] = not val

        # Pre-set master key if needed
        master_cb_key = f"_catcb_{active_stage}_all"
        if master_cb_key not in st.session_state:
            st.session_state[master_cb_key] = all_selected
        st.session_state[master_cb_key] = all_selected  # keep in sync

        st.checkbox(
            f"Все категории ({total_count})",
            key=master_cb_key,
            on_change=_on_master,
        )

        # --- Категории и подкатегории ---
        selected_subs: dict = st.session_state[_subcat_sess_key(active_stage)]

        for cat_code, cat_info in sorted(
            hierarchy.items(),
            key=lambda x: (-x[1]["count"], x[0]),
        ):
            cat_cb_key = f"_catcb_{active_stage}_{cat_code}"
            cat_val = cat_code in selected_cats

            # Sync display value before render
            if cat_cb_key not in st.session_state:
                st.session_state[cat_cb_key] = cat_val
            st.session_state[cat_cb_key] = cat_val

            # Closure capture via default arg
            def _on_cat_change(
                _stage=active_stage,
                _cat=cat_code,
                _subs=cat_info["subcategories"],
            ) -> None:
                val = st.session_state[f"_catcb_{_stage}_{_cat}"]
                cur_cats: set = st.session_state[_cat_sess_key(_stage)]
                cur_subs: dict = st.session_state[_subcat_sess_key(_stage)]
                if val:
                    cur_cats.add(_cat)
                    cur_subs[_cat] = set(_subs.keys())
                else:
                    cur_cats.discard(_cat)
                    cur_subs[_cat] = set()
                st.session_state[_cat_sess_key(_stage)] = cur_cats
                st.session_state[_subcat_sess_key(_stage)] = cur_subs
                st.session_state[f"_catf_{_stage}_explicit"] = True

            st.checkbox(
                f"**{cat_info['display']}** ({cat_info['count']})",
                key=cat_cb_key,
                on_change=_on_cat_change,
            )

            # Subcategories (indented with nbsp)
            for sub_code, sub_info in sorted(
                cat_info["subcategories"].items(),
                key=lambda x: (-x[1]["count"], x[0]),
            ):
                sub_cb_key = f"_catcb_{active_stage}_{cat_code}__{sub_code}"
                sub_val = sub_code in selected_subs.get(cat_code, set())

                if sub_cb_key not in st.session_state:
                    st.session_state[sub_cb_key] = sub_val
                st.session_state[sub_cb_key] = sub_val

                def _on_sub_change(
                    _stage=active_stage,
                    _cat=cat_code,
                    _sub=sub_code,
                ) -> None:
                    val = st.session_state[f"_catcb_{_stage}_{_cat}__{_sub}"]
                    cur_cats: set = st.session_state[_cat_sess_key(_stage)]
                    cur_subs: dict = st.session_state[_subcat_sess_key(_stage)]
                    subs_set: set = cur_subs.get(_cat, set())
                    if val:
                        subs_set.add(_sub)
                        cur_cats.add(_cat)
                    else:
                        subs_set.discard(_sub)
                    cur_subs[_cat] = subs_set
                    st.session_state[_cat_sess_key(_stage)] = cur_cats
                    st.session_state[_subcat_sess_key(_stage)] = cur_subs

                st.checkbox(
                    f"   {sub_info['display']} ({sub_info['count']})",
                    key=sub_cb_key,
                    on_change=_on_sub_change,
                )


@st.cache_data(ttl=300, show_spinner=False)
def _load_regions_from_db() -> list[str]:
    """Уникальные delivery_region из crm_procurements, отсортированные по частоте."""
    import logging, os, traceback
    import psycopg2
    _log = logging.getLogger(__name__)
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs
    PG = require_crm_db_connect_kwargs()
    try:
        conn = psycopg2.connect(connect_timeout=5, options="-c statement_timeout=20000", **PG)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT delivery_region, COUNT(*) AS cnt
                FROM crm_procurements
                WHERE delivery_region IS NOT NULL AND delivery_region != ''
                GROUP BY delivery_region
                ORDER BY cnt DESC, delivery_region
                LIMIT 100
            """)
            regions = [row[0] for row in cur.fetchall()]
        conn.close()
        if not regions:
            _log.warning("_load_regions_from_db: query returned 0 rows (host=%s db=%s)", PG['host'], PG['dbname'])
        return regions
    except Exception:
        err = traceback.format_exc()
        _log.error("_load_regions_from_db FAILED (host=%s db=%s):\n%s", PG['host'], PG['dbname'], err)
        st.caption("Регионы: нет данных из базы — фильтр временно недоступен.")
        return []


@st.cache_data(ttl=120, show_spinner=False)
def _load_categories_from_db() -> list[str]:
    """Уникальные crm_category из crm_procurements (запасной вариант)."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from src.services.crm_db_runtime import require_crm_db_connect_kwargs
        conn = psycopg2.connect(
            connect_timeout=5,
            options="-c statement_timeout=20000",
            **require_crm_db_connect_kwargs(),
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT crm_category FROM crm_procurements
                WHERE crm_category IS NOT NULL AND crm_category != ''
                ORDER BY crm_category
            """)
            cats = [r["crm_category"] for r in cur.fetchall()]
        conn.close()
        return cats
    except Exception:
        return []
