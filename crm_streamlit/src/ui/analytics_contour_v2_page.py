"""Страница аналитического контура v2 (§14.1–14.3)."""
from __future__ import annotations

import streamlit as st

from src.ui.components.analytics_v2.analytics_expander import render_charts
from src.ui.components.analytics_v2.header import render_header
from src.ui.components.analytics_v2.kpi_row import render_kpi_row
from src.ui.components.analytics_v2.limits import render_limits
from src.ui.components.analytics_v2.mock_data import CARDS
from src.ui.components.analytics_v2.quick_filters import render_quick_filters
from src.ui.components.analytics_v2.tabs import render_tabs

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
    """Шапка → KPI → Лимит → Три графика → [Фильтры | Рабочая область]."""
    st.session_state["analytics_v2_cards"] = CARDS

    st.markdown(_STICKY_CSS, unsafe_allow_html=True)

    st.caption("CRM build: f910bd3+fix-torgi-lifecycle")
    render_header()
    render_kpi_row()
    render_limits()
    st.divider()
    render_charts()
    st.divider()

    left, right = st.columns([1, 3], gap="medium")

    with left:
        _render_filters()

    with right:
        render_quick_filters()
        render_tabs()


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


def _reset_all_category_filters(session: dict | None = None) -> None:
    """Удаляет все category filter ключи из session_state."""
    session = session if session is not None else st.session_state
    for stage in _STAGES:
        for k in [_cat_sess_key(stage), _subcat_sess_key(stage)]:
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
                st.rerun()
        with b2:
            if st.button("Снять всё", key=f"_catf_{active_stage}_btn_none",
                         use_container_width=True):
                st.session_state[_cat_sess_key(active_stage)] = set()
                st.session_state[_subcat_sess_key(active_stage)] = {
                    cat: set() for cat in hierarchy
                }
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
        conn = psycopg2.connect(connect_timeout=5, **PG)
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
        st.caption(f"⚠️ Регионы: ошибка соединения ({PG['host']}:{PG['port']}/{PG['dbname']}) — см. лог")
        return []


@st.cache_data(ttl=120, show_spinner=False)
def _load_categories_from_db() -> list[str]:
    """Уникальные crm_category из crm_procurements (запасной вариант)."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from src.services.crm_db_runtime import require_crm_db_connect_kwargs
        conn = psycopg2.connect(**require_crm_db_connect_kwargs())
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
