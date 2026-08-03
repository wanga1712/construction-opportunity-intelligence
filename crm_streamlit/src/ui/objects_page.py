"""Страница закупочного контура: аналитика стадий, динамические категории и карточки."""
from __future__ import annotations

from typing import Optional, Sequence, Set

import pandas as pd
import streamlit as st

from src.constants.object_quality import OBJECT_QUALITY_TIERS
from src.constants.object_segments import OBJECT_SEGMENT_TABS, OBJECT_SOURCE_OPTIONS
from src.services.companies_service import CompaniesService
from src.services.docs_match_preview import confirmed_product_groups
from src.services.object_enrich import enrich_tender_items
from src.services.object_pipeline_stage import PIPELINE_STAGE_OPTIONS
from src.services.objects_service import ObjectsService, filter_objects
from src.ui.card_pagination import render_card_grid_with_pagination
from src.ui.object_card import render_object_cards_batch
from src.ui.object_detail import render_object_detail
from src.ui.objects_page_panels import (
    render_ai_resegment_panel,
    render_docs_priority_panel,
    render_index_panel,
    render_leads_bridge_panel,
    render_legend,
)
from src.ui.session_deps import get_objects_service


def _checkbox_codes(*, key_prefix: str, label: str, options: Sequence[tuple[str, str]], default_all: bool = True, columns: int = 4) -> set[str]:
    st.markdown(f"**{label}**")
    selected: set[str] = set()
    cols = st.columns(max(1, columns))
    for idx, (code, option_label) in enumerate(options):
        with cols[idx % len(cols)]:
            if st.checkbox(option_label, value=default_all, key=f"{key_prefix}_{code}"):
                selected.add(code)
    return selected


def _stage_title(label: str) -> str:
    return label.split(")", 1)[-1].strip() if ")" in label else label


def _dynamic_groups(objects_service: ObjectsService) -> list[tuple[str, str]]:
    groups = objects_service.dynamic_product_groups(include_computers=False)
    st.session_state["objects_product_group_options"] = groups
    return groups


def _product_group_counts(items) -> list[tuple[str, int]]:
    result = []
    groups = [code for code, _ in st.session_state.get("objects_product_group_options", []) if code != "computers"]
    counts = {code: 0 for code in groups}
    for item in items:
        found = confirmed_product_groups(item)
        for code in groups:
            if code in found:
                counts[code] += 1
    for code, label in st.session_state.get("objects_product_group_options", []):
        if code in counts and counts[code] > 0:
            result.append((label, counts[code]))
    return result


def _render_hero(objects_service: ObjectsService, base_items) -> None:
    stage_counts = {code: sum(1 for o in base_items if (o.pipeline_stage_code or "news_signal") == code) for code, _ in PIPELINE_STAGE_OPTIONS}
    tier_counts = {code: sum(1 for o in base_items if (o.quality_tier or "") == code) for code, _ in OBJECT_QUALITY_TIERS}
    docs_count = sum(1 for o in base_items if (o.doc_matches or 0) > 0)
    confident_count = sum(1 for o in base_items if (o.doc_matches or 0) > 0 and (o.ai_classification_confidence or 0) >= 60)

    meta = objects_service.index_meta()
    index_at = str(meta.get("indexed_at") or "—")[:19]
    enrich_age = objects_service.dynamic_enrich_age_sec
    enrich_label = "не считалось" if enrich_age is None else f"{enrich_age // 60}м {enrich_age % 60:02d}с"

    st.markdown(
        f"""
        <div style="padding:14px 16px;border-radius:16px;background:linear-gradient(135deg, rgba(1,118,211,.16), rgba(1,118,211,.04));
        border:1px solid rgba(1,118,211,.18);margin:0.15rem 0 0.9rem 0;">
          <div style="font-size:13px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:#01579B;">
            Коммерческий аналитический контур
          </div>
          <div style="font-size:20px;font-weight:900;margin-top:4px;">
            0 новость → 1 проект → 2 экспертиза → 3 ожидание стройки → 4 торги → 5 разыграны
          </div>
          <div style="font-size:13px;margin-top:4px;color:#5F6B7A;">
            Индекс CRM: {meta.get("row_count") or 0} · обновлён {index_at} · динамическое обогащение: {enrich_label}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Новые", stage_counts.get("news_signal", 0))
    c2.metric("Проекты", stage_counts.get("project_design_ai", 0))
    c3.metric("Экспертиза", stage_counts.get("positive_expertise", 0))
    c4.metric("Торги", stage_counts.get("construction_active", 0))
    c5.metric("Разыграны", stage_counts.get("works_awarded", 0))

    c6, c7, c8, c9 = st.columns(4)
    c6.metric("С документами", docs_count)
    c7.metric("Уверенные docs+AI", confident_count)
    c8.metric("Золото", tier_counts.get("gold", 0))
    c9.metric("Серебро", tier_counts.get("silver", 0))

    stage_df = pd.DataFrame(
        [{"Этап": _stage_title(label), "Карточки": stage_counts.get(code, 0)} for code, label in PIPELINE_STAGE_OPTIONS]
    )
    groups = _product_group_counts(base_items)
    group_df = pd.DataFrame(groups, columns=["Группа", "Карточки"]) if groups else pd.DataFrame([{"Группа": "Нет совпадений", "Карточки": 0}])

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Распределение по этапам**")
        st.bar_chart(stage_df.set_index("Этап"), use_container_width=True)
    with g2:
        st.markdown("**Карточки по товарным группам**")
        st.bar_chart(group_df.set_index("Группа"), use_container_width=True)

    st.caption(
        "Главная логика: экран сначала показывает аналитику и динамические категории из CRM, "
        "а фильтры и карточки идут ниже."
    )


def _render_top_controls(objects_service: ObjectsService) -> tuple[str, str, list[tuple[str, str]]]:
    groups = _dynamic_groups(objects_service)
    top_left, top_right = st.columns([3, 1])
    with top_left:
        st.markdown("### АНАЛИТИЧЕСКИЙ КОНТУР")
        st.caption("Главная / Новые карточки / Портфель / Обновления / Компании / Аналитика")
    with top_right:
        category = st.selectbox(
            "Категория",
            ["Все категории"] + [label for _, label in groups],
            key="objects_top_category",
        )
        period = st.selectbox(
            "Период",
            ["7 дней", "30 дней", "90 дней"],
            key="objects_top_period",
        )
    return category, period, groups


def _render_filters(objects_service: ObjectsService) -> tuple:
    st.markdown("#### Поиск и фильтры")
    regions = objects_service.available_regions()
    region_options = ["Все регионы"] + [name for _, name in regions]
    region_id_map = {name: rid for rid, name in regions}

    c1, c2 = st.columns([3, 1])
    with c1:
        search = st.text_input(
            "Поиск объекта",
            placeholder="Название, адрес, № закупки, № экспертизы/ПД, ИНН",
            key="objects_search",
        )
    with c2:
        if st.button("Найти", key="objects_search_btn", use_container_width=True):
            st.session_state["objects_search_active"] = search
            st.session_state.pop("objects_service", None)
            st.rerun()

    c3, c4, c5 = st.columns([2, 1.2, 1])
    with c3:
        region_label = st.selectbox("Регион", region_options, key="objects_region")
    with c4:
        page_size = st.selectbox("На странице", [12, 24, 48], index=1, key="objects_page_size")
    with c5:
        if st.button("↻", key="objects_refresh", use_container_width=True, help="Сбросить кэш"):
            st.session_state.pop("objects_service", None)
            st.rerun()

    selected_tier_codes = _checkbox_codes(
        key_prefix="objects_tier",
        label="Уровень данных (медали карточек)",
        options=OBJECT_QUALITY_TIERS,
        default_all=True,
        columns=4,
    )
    selected_source_codes = _checkbox_codes(
        key_prefix="objects_source",
        label="Источник",
        options=tuple((code, label) for code, label in OBJECT_SOURCE_OPTIONS if code != "nashdom"),
        default_all=True,
        columns=4,
    )
    selected_pipeline_stage_codes = _checkbox_codes(
        key_prefix="objects_pipeline_stage",
        label="Этапы воронки",
        options=PIPELINE_STAGE_OPTIONS,
        default_all=True,
        columns=2,
    ) or {code for code, _ in PIPELINE_STAGE_OPTIONS}

    product_group_options = _dynamic_groups(objects_service)
    selected_product_codes = _checkbox_codes(
        key_prefix="objects_product",
        label="Товарные направления",
        options=(("all", "Все направления"),) + tuple(product_group_options),
        default_all=True,
        columns=4,
    ) or {"all"}
    selected_segment_codes = _checkbox_codes(
        key_prefix="objects_segment",
        label="Сегменты",
        options=OBJECT_SEGMENT_TABS,
        default_all=True,
        columns=3,
    ) or {code for code, _ in OBJECT_SEGMENT_TABS}

    return (
        search,
        page_size,
        set(selected_source_codes),
        None if region_label == "Все регионы" else region_id_map.get(region_label),
        selected_tier_codes,
        selected_product_codes,
        selected_segment_codes,
        selected_pipeline_stage_codes,
        product_group_options,
    )


def _matches_product_group(item, product_group: str) -> bool:
    return product_group == "all" or product_group in confirmed_product_groups(item)


def _apply_list_filters(all_raw, *, pipeline_stage: str, seg_code: Optional[str], product_code: str, sources, display_search, region_id, selected_tier_codes):
    items = filter_objects(all_raw, segment=seg_code, sources=sources, search=display_search, region_id=region_id)
    items = [o for o in items if (o.pipeline_stage_code or "news_signal") == pipeline_stage]
    if selected_tier_codes and len(selected_tier_codes) < len(OBJECT_QUALITY_TIERS):
        items = [o for o in items if o.quality_tier in selected_tier_codes]
    if product_code != "all":
        items = [o for o in items if _matches_product_group(o, product_code)]
    return items


def render_objects_page(service: CompaniesService) -> None:
    objects_service = get_objects_service(service)
    search_q = st.session_state.get("objects_search_active", "")

    detail_key = st.session_state.get("object_detail_key")
    if detail_key:
        with st.spinner("Загрузка объекта…"):
            if not objects_service.load_sync(search_query=search_q if search_q else ""):
                st.error(objects_service.last_error or "Не удалось загрузить объекты")
                if st.button("← К радару объектов", key="objects_back_load_err"):
                    _clear_object_detail()
                return
        render_object_detail(objects_service, detail_key, on_back=_clear_object_detail)
        return

    st.title("Закупочный контур")
    st.caption("Аналитика по стадиям, динамические категории из CRM, затем карточки и фильтры.")

    with st.spinner("Загрузка закупочного контура…"):
        if not objects_service.load_sync(search_query=search_q if search_q else ""):
            st.error(objects_service.last_error or "Не удалось загрузить объекты")
            return

    if not objects_service.has_index() and not objects_service.all_objects():
        st.info("Постройте индекс в блоке «Служебное» ниже.")
        with st.expander("Служебное", expanded=True):
            render_index_panel(service, objects_service)
        return

    all_raw = objects_service.all_objects()
    base_items = filter_objects(all_raw)

    render_legend()
    category_label, period_label, product_group_options = _render_top_controls(objects_service)
    _render_hero(objects_service, base_items)

    tabs = st.tabs(["Главная", "Новые карточки", "Портфель", "Обновления", "Компании", "Аналитика"])

    (
        search,
        page_size,
        sources,
        region_id,
        selected_tier_codes,
        selected_product_codes,
        selected_segment_codes,
        selected_pipeline_stage_codes,
        _,
    ) = _render_filters(objects_service)

    display_search = search or search_q

    def enrich_page(page_items) -> None:
        enrich_tender_items(objects_service.tender_db, page_items)

    product_labels = dict((("all", "Все направления"),) + tuple(product_group_options))
    pipeline_labels = dict(PIPELINE_STAGE_OPTIONS)
    segment_labels = dict(OBJECT_SEGMENT_TABS)

    with tabs[0]:
        st.markdown(f"**Категория:** {category_label} · **Период:** {period_label}")
        st.info("Здесь первая аналитика, стадии, категории и общий входной поток.")

    def render_stage_tab(stage_code: str) -> None:
        stage_items = _apply_list_filters(
            all_raw,
            pipeline_stage=stage_code,
            seg_code=None,
            product_code="all",
            sources=sources,
            display_search=display_search,
            region_id=region_id,
            selected_tier_codes=selected_tier_codes,
        )
        if not stage_items:
            st.info("Нет объектов на этом этапе.")
            return
        for product_code, _product_label in (("all", "Все направления"),) + tuple(product_group_options):
            if product_code not in selected_product_codes:
                continue
            product_items = _apply_list_filters(
                all_raw,
                pipeline_stage=stage_code,
                seg_code=None,
                product_code=product_code,
                sources=sources,
                display_search=display_search,
                region_id=region_id,
                selected_tier_codes=selected_tier_codes,
            )
            if not product_items:
                continue
            st.markdown(f"**{product_labels.get(product_code, product_code)}** ({len(product_items)})")
            for seg_code, _seg_label in OBJECT_SEGMENT_TABS:
                if seg_code not in selected_segment_codes:
                    continue
                filtered = _apply_list_filters(
                    all_raw,
                    pipeline_stage=stage_code,
                    seg_code=seg_code,
                    product_code=product_code,
                    sources=sources,
                    display_search=display_search,
                    region_id=region_id,
                    selected_tier_codes=selected_tier_codes,
                )
                if not filtered:
                    continue
                st.caption(f"{segment_labels.get(seg_code, seg_code)} · {len(filtered)}")

                def render_page(page_items, page: int, _seg=seg_code, _prod=product_code, _pipe=stage_code) -> None:
                    render_object_cards_batch(page_items, tab_key=f"objects_{_pipe}_{_prod}_{_seg}", page=page, active_product_group=_prod if _prod != "all" else None)

                render_card_grid_with_pagination(filtered, tab_key=f"objects_{stage_code}_{product_code}_{seg_code}", page_size=int(page_size), render_batch=render_page, before_render=enrich_page)

    with tabs[1]:
        render_stage_tab("news_signal")
    with tabs[2]:
        render_stage_tab("project_design_ai")
    with tabs[3]:
        render_stage_tab("positive_expertise")
    with tabs[4]:
        st.info("Здесь можно собрать портфель объектов и выбрать важные карточки вручную.")
        render_stage_tab("construction_active")
    with tabs[5]:
        st.info("Аналитический режим: сводные графики, качество AI, обновления и служебные панели.")
        st.caption("Текущий экран использует те же данные, но выводит их в более плотном аналитическом виде.")

    # Fallback list for remaining stages if selected in filters.
    for pipeline_code, pipeline_label in PIPELINE_STAGE_OPTIONS:
        if pipeline_code in {"news_signal", "project_design_ai", "positive_expertise"}:
            continue
        if pipeline_code not in selected_pipeline_stage_codes:
            continue
        stage_items = _apply_list_filters(
            all_raw,
            pipeline_stage=pipeline_code,
            seg_code=None,
            product_code="all",
            sources=sources,
            display_search=display_search,
            region_id=region_id,
            selected_tier_codes=selected_tier_codes,
        )
        if not stage_items:
            continue
        st.markdown(f"### {_stage_title(pipeline_labels.get(pipeline_code, pipeline_label))} ({len(stage_items)})")
        for product_code, _product_label in (("all", "Все направления"),) + tuple(product_group_options):
            if product_code not in selected_product_codes:
                continue
            filtered = _apply_list_filters(
                all_raw,
                pipeline_stage=pipeline_code,
                seg_code=None,
                product_code=product_code,
                sources=sources,
                display_search=display_search,
                region_id=region_id,
                selected_tier_codes=selected_tier_codes,
            )
            if not filtered:
                continue
            render_card_grid_with_pagination(
                filtered,
                tab_key=f"objects_{pipeline_code}_{product_code}",
                page_size=int(page_size),
                render_batch=lambda page_items, page, _p=pipeline_code, _prod=product_code: render_object_cards_batch(page_items, tab_key=f"objects_{_p}_{_prod}_fallback", page=page, active_product_group=_prod if _prod != "all" else None),
                before_render=enrich_page,
            )

    with st.expander("Служебное (индекс, AI, CRM)", expanded=False):
        st.caption(objects_service.settings_summary)
        render_index_panel(service, objects_service)
        render_ai_resegment_panel(objects_service)
        render_docs_priority_panel(objects_service)
        render_leads_bridge_panel(objects_service)


def _clear_object_detail() -> None:
    st.session_state.pop("object_detail_key", None)
    st.rerun()
