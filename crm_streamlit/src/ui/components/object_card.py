"""Карточки объектов для аналитического контура."""
from __future__ import annotations

import streamlit as st

from src.constants.object_quality import TIER_BADGE_COLORS, TIER_CARD_BG
from src.services.docs_match_preview import confirmed_product_groups, products_for_group
from src.services.object_category_labels import SEGMENT_LABELS, default_label_for_item

TIER_TITLES = {"gold": "ЗОЛОТАЯ КАРТОЧКА", "silver": "СЕРЕБРЯНАЯ КАРТОЧКА", "bronze": "БРОНЗОВАЯ КАРТОЧКА", "wood": "РАННЯЯ КАРТОЧКА", "basic": "РАННЯЯ КАРТОЧКА"}


@st.dialog("Карточка объекта")
def open_card_dialog(object_key: str, object_name: str) -> None:
    """Открываем полную карточку объекта."""
    st.write(object_name)
    left, right = st.columns(2)
    if left.button("Отмена", use_container_width=True):
        st.rerun()
    if right.button("Открыть", type="primary", use_container_width=True):
        opened = set(st.session_state.get("opened_cards", []))
        opened.add(object_key)
        st.session_state["opened_cards"] = sorted(opened)
        st.session_state["selected_object_id"] = object_key
        st.query_params.update({"object_id": object_key})
        st.rerun()


def _db_value(value: str | None) -> str:
    """Красиво подсвечиваем отсутствие данных в БД."""
    clean = str(value or "").strip()
    if clean:
        return clean
    return '<span style="color:#b42318;font-weight:700;">Не найдено в БД</span>'


def _tier(item) -> str:
    """Нормализуем уровень карточки."""
    return (item.quality_tier or "wood").lower()


def _badge_html(item) -> str:
    """Бейдж уровня карточки."""
    tier = _tier(item)
    bg, text = TIER_BADGE_COLORS.get(tier, TIER_BADGE_COLORS["wood"])
    title = TIER_TITLES.get(tier, TIER_TITLES["wood"])
    return (
        f'<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
        f'background:{bg};color:{text};font-size:12px;font-weight:700;">{title}</span>'
    )


def _object_kind(item) -> str:
    """Тип объекта для человека."""
    if item.segment in SEGMENT_LABELS:
        return SEGMENT_LABELS[item.segment]
    return default_label_for_item(item)


def _categories(item, groups_map: dict[str, str]) -> str:
    """Категории через запятую."""
    codes = sorted(confirmed_product_groups(item))
    if not codes:
        return ""
    return ", ".join(groups_map.get(code, code) for code in codes)


def _found_summary(item) -> str:
    """Кратко показываем, что реально нашли в документах."""
    values = list(item.matched_product_preview or [])[:4]
    return ", ".join(values)


def _material(item, groups_map: dict[str, str]) -> str:
    """Ключевой материал для строки карточки."""
    for code in sorted(confirmed_product_groups(item)):
        found = products_for_group(item, code)
        if found:
            return ", ".join(found[:3])
    return _found_summary(item)


def _updated(item) -> str:
    """Отображаем дату обновления."""
    for field in ("updated_at", "delivery_end_date", "delivery_start_date", "end_date", "start_date"):
        value = getattr(item, field, None)
        if value:
            return str(value)[:10]
    return ""


def _tender_link(item) -> str:
    """Ссылка на закупку, если она есть в объекте."""
    for field in ("purchase_url", "tender_url", "source_url", "url"):
        value = getattr(item, field, None)
        if value:
            href = str(value).strip()
            return f'<a href="{href}" target="_blank">Открыть закупку</a>'
    return _db_value("")


def _next_step(item) -> str:
    """Следующий шаг из БД или AI-поля."""
    return str(item.ai_manager_next_step or "").strip()


def _reason(item) -> str:
    """Причина уровня/рейтинга."""
    return str(item.ai_card_status_reason or item.ai_priority_reason or "").strip()


def _designer(item) -> str:
    """Пытаемся взять проектировщика из известных полей."""
    return str(item.expertise_planner or item.expertise_developer or "").strip()


def _field(label: str, value: str | None) -> None:
    """Единый рендер поля карточки."""
    st.markdown(
        f"""
        <div style="font-size:12px;color:#667085;margin-bottom:2px;">{label}</div>
        <div style="font-size:15px;font-weight:600;margin-bottom:8px;">{_db_value(value)}</div>
        """,
        unsafe_allow_html=True,
    )


def render_object_card(item, groups_map: dict[str, str], key_prefix: str = "cards") -> None:
    """Рисуем превью-карточку с реальными данными из БД."""
    tier = _tier(item)
    card_bg = TIER_CARD_BG.get(tier, TIER_CARD_BG["wood"])
    title = str(item.name or "").strip() or "Не найдено в БД"
    region = str(item.region or item.address or "").strip()
    object_kind = _object_kind(item)

    st.markdown(
        f'<div style="background:{card_bg};border:1px solid rgba(49,51,63,.12);'
        f'border-radius:16px;padding:14px 16px;margin-bottom:16px;">',
        unsafe_allow_html=True,
    )
    with st.container():
        head_left, head_right = st.columns([5, 1.4], gap="large")
        with head_left:
            st.markdown(_badge_html(item), unsafe_allow_html=True)
            st.markdown(f"### {title}")
            st.markdown(
                f'<div style="font-size:15px;color:#344054;margin-bottom:10px;">'
                f'{_db_value(region)} / {_db_value(object_kind)}</div>',
                unsafe_allow_html=True,
            )

            row1 = st.columns(4)
            with row1[0]:
                _field("Стадия", getattr(item, "pipeline_stage_label", None))
            with row1[1]:
                _field("Категория", _categories(item, groups_map))
            with row1[2]:
                _field("Обновлено", _updated(item))
            with row1[3]:
                _field("Ссылка на закупку", _tender_link(item))

            row2 = st.columns(4)
            with row2[0]:
                _field("Что найдено кратко", _found_summary(item))
            with row2[1]:
                _field("Материал", _material(item, groups_map))
            with row2[2]:
                _field("Объём", getattr(item, "docs_volume_preview", None))
            with row2[3]:
                _field("Следующий этап", _next_step(item))

            row3 = st.columns(3)
            with row3[0]:
                _field("Балансодержатель / заказчик", item.balance_holder or item.customer_name)
            with row3[1]:
                _field("Проектировщик", _designer(item))
            with row3[2]:
                _field("Подрядчик", getattr(item, "contractor_name", None))

            st.markdown(
                f'<div style="padding:8px 10px;border-radius:10px;background:rgba(255,255,255,.40);'
                f'font-size:14px;"><strong>Причина рейтинга:</strong> {_db_value(_reason(item))}</div>',
                unsafe_allow_html=True,
            )

        with head_right:
            if st.button("Открыть", key=f"{key_prefix}_open_{item.key}", use_container_width=True):
                open_card_dialog(item.key, item.name)
            if st.button("В портфель", key=f"{key_prefix}_portfolio_{item.key}", use_container_width=True):
                opened = set(st.session_state.get("opened_cards", []))
                opened.add(item.key)
                st.session_state["opened_cards"] = sorted(opened)
                st.success("Добавлено")
            if st.button("Доказательства", key=f"{key_prefix}_proof_{item.key}", use_container_width=True):
                st.session_state["selected_object_id"] = item.key
                st.query_params.update({"object_id": item.key})
                st.rerun()
            if st.button("Похожие", key=f"{key_prefix}_similar_{item.key}", use_container_width=True):
                st.info("Похожие объекты откроются в полной карточке.")
    st.markdown("</div>", unsafe_allow_html=True)


@st.fragment
def render_object_cards(items, groups_map: dict[str, str], key_prefix: str = "cards") -> None:
    """Рендерим ленту карточек."""
    for item in items:
        render_object_card(item, groups_map, key_prefix=key_prefix)
