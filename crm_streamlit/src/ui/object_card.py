"""Превью-карточка объекта в закупочном контуре."""
from __future__ import annotations

import hashlib
import html
import re
from typing import Callable, Optional, Sequence

import streamlit as st

from modules.crm.analytics.object_classifier import segment_label
from src.constants.object_quality import (
    TIER_BADGE_COLORS,
    TIER_BORDER_COLORS,
    TIER_CARD_BG,
    TIER_LABELS,
)
from src.constants.product_groups import PRODUCT_GROUP_OPTIONS
from src.services.docs_match_preview import (
    confirmed_product_groups,
    other_product_groups,
    products_for_group,
)
from src.services.object_pipeline_stage import PIPELINE_STAGE_OPTIONS
from src.services.object_models import ObjectViewItem
from src.ui.object_card_format import fmt_date, is_awarded_registry

_LEGAL_TAIL_RE = re.compile(
    r"\s*\((?:ОГРН|ИНН|КПП|МЕСТО НАХОЖДЕНИЯ)[^)]*\)\s*",
    re.IGNORECASE,
)


def _short_name(raw: Optional[str], *, max_len: int = 72) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = _LEGAL_TAIL_RE.sub("", text).strip(" ,;")
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def _party_line(item: ObjectViewItem, awarded: bool) -> str:
    bits: list[str] = []
    balance = _short_name(item.balance_holder)
    organizer = _short_name(item.customer_name)
    if balance:
        bits.append(f"Заказчик: {html.escape(balance)}")
    elif organizer:
        bits.append(f"Организатор: {html.escape(organizer)}")
    if awarded and item.contractor_name:
        bits.append(f"Подрядчик: {html.escape(_short_name(item.contractor_name))}")
    return " · ".join(bits)


def _dates_line(item: ObjectViewItem, awarded: bool) -> str:
    if awarded and (item.delivery_start_date or item.delivery_end_date):
        return f"Поставка {fmt_date(item.delivery_start_date)} — {fmt_date(item.delivery_end_date)}"
    if item.start_date or item.end_date:
        return f"Торги {fmt_date(item.start_date)} — {fmt_date(item.end_date)}"
    return ""


def _docs_block(item: ObjectViewItem, *, active_product_group: Optional[str]) -> str:
    """Человекочитаемый блок: что именно найдено в документах."""
    groups = confirmed_product_groups(item)
    if not groups and not (item.doc_matches or item.matched_files):
        return (
            '<div style="margin-top:8px;color:#8A6A00;font-size:12px;">'
            "В документах совпадений по материалам пока нет</div>"
        )

    labels = dict(PRODUCT_GROUP_OPTIONS)
    lines: list[str] = []
    order = [code for code, _ in PRODUCT_GROUP_OPTIONS if code in groups]
    if active_product_group and active_product_group != "all" and active_product_group in order:
        order = [active_product_group] + [c for c in order if c != active_product_group]

    for code in order[:4]:
        products = products_for_group(item, code)[:3]
        label = labels.get(code, code)
        if products:
            prod = ", ".join(html.escape(p) for p in products)
            lines.append(f"<b>{html.escape(label)}:</b> {prod}")
        else:
            lines.append(f"<b>{html.escape(label)}</b>")

    n_matches = int(item.doc_matches or 0)
    n_files = int(item.matched_files or 0)
    footer = f"{n_matches} совп. · {n_files} файл." if n_files else f"{n_matches} совпадений"
    vol = (item.docs_volume_preview or "").strip()
    if vol and "не извлеч" not in vol.lower():
        footer += f" · объём: {html.escape(vol)}"

    body = "<br/>".join(lines) if lines else "есть совпадения (названия продуктов не разобраны)"
    return (
        '<div style="margin-top:8px;padding:8px 10px;background:rgba(255,255,255,.55);'
        'border-radius:6px;font-size:12px;color:#1a1a1a;">'
        '<div style="font-weight:700;color:#0B5CAB;margin-bottom:4px;">Найдено в документах</div>'
        f"{body}"
        f'<div style="margin-top:4px;color:#555;font-size:11px;">{footer}</div>'
        "</div>"
    )


def build_card_body(item: ObjectViewItem, *, active_product_group: Optional[str] = None) -> str:
    tier = (item.quality_tier or item.ai_card_status_code or "wood").lower()
    border = TIER_BORDER_COLORS.get(tier, "#C9C9C9")
    bg, fg = TIER_BADGE_COLORS.get(tier, ("#F3F3F3", "#706E6B"))
    card_bg = TIER_CARD_BG.get(tier, "#FFFFFF")
    tier_label = TIER_LABELS.get(tier, "Карточка")
    awarded = is_awarded_registry(item.registry_type)
    stage_labels = dict(PIPELINE_STAGE_OPTIONS)
    stage_label = stage_labels.get(item.pipeline_stage_code or "news_signal", "0) Новостной сигнал")

    place = html.escape(item.region or item.address or "")
    if item.address and item.region and item.region not in item.address:
        place = f"{html.escape(_short_name(item.address, max_len=90))} · {html.escape(item.region)}"
    elif item.address:
        place = html.escape(_short_name(item.address, max_len=110))

    meta_bits = []
    if item.status:
        meta_bits.append(html.escape(item.status))
    if stage_label:
        meta_bits.append(html.escape(stage_label))
    dates = _dates_line(item, awarded)
    if dates:
        meta_bits.append(html.escape(dates))
    meta = " · ".join(meta_bits)

    party = _party_line(item, awarded)
    docs = _docs_block(item, active_product_group=active_product_group)

    ai_line = ""
    if item.ai_priority_score:
        bits = [f"AI {int(item.ai_priority_score)}"]
        if item.ai_delivery_chance:
            bits.append(f"шанс {html.escape(item.ai_delivery_chance)}")
        ai_line = " · ".join(bits)

    parts = [
        f'<div style="border-left:6px solid {border};background:{card_bg};'
        f'border-radius:10px;padding:12px 14px;line-height:1.4;font-size:13px;'
        f'box-shadow:0 1px 5px rgba(0,0,0,.07);">',
        '<div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">',
        f'<div style="font-weight:700;color:#111;font-size:14px;flex:1;">'
        f'{html.escape(item.name)}</div>',
        f'<span style="background:{bg};color:{fg};padding:5px 12px;border-radius:999px;'
        f'font-size:12px;font-weight:800;white-space:nowrap;border:1px solid {border};">'
        f'{html.escape(tier_label)}</span>',
        "</div>",
    ]
    if place:
        parts.append(f'<div style="color:#555;margin-top:4px;font-size:12px;">{place}</div>')
    if meta:
        parts.append(f'<div style="color:#333;margin-top:4px;font-size:12px;font-weight:600;">{meta}</div>')
    if party:
        parts.append(f'<div style="color:#444;margin-top:6px;font-size:12px;">{party}</div>')
    if (item.pipeline_stage_code or "news_signal") == "news_signal":
        parts.append(
            '<div style="margin-top:6px;color:#8A6A00;font-size:12px;font-weight:600;">'
            'Ранний сигнал: пока только новости или внешний намёк на объект'
            '</div>'
        )
    parts.append(docs)
    if ai_line:
        parts.append(
            f'<div style="margin-top:6px;color:#1B5E20;font-size:12px;font-weight:600;">{ai_line}</div>'
        )
    parts.append(
        f'<div style="color:#777;font-size:11px;margin-top:6px;text-align:right;">'
        f'{html.escape(segment_label(item.segment))}</div>'
    )
    parts.append("</div>")
    return "".join(parts)


def _open_detail(object_key: str) -> None:
    st.session_state["object_detail_key"] = object_key
    st.session_state["nav_page"] = "objects"


def stable_card_key(object_key: str, tab_key: str, page: int) -> str:
    digest = hashlib.md5(f"{tab_key}:{page}:{object_key}".encode("utf-8")).hexdigest()[:24]
    return f"obj_{digest}"


def _open_detail_with_group(object_key: str, product_group: Optional[str] = None) -> None:
    st.session_state["object_detail_key"] = object_key
    st.session_state["nav_page"] = "objects"
    if product_group and product_group != "all":
        st.session_state["object_detail_product_group"] = product_group
    else:
        st.session_state.pop("object_detail_product_group", None)


def _render_related_group_links(
    item: ObjectViewItem,
    *,
    active_product_group: Optional[str],
    tab_key: str,
    page: int,
) -> None:
    links = other_product_groups(item, active_product_group)
    # Только направления, где реально есть продукты
    links = [(c, lab) for c, lab in links if products_for_group(item, c)]
    if not links:
        return
    st.caption("Ещё направления в этой закупке:")
    cols = st.columns(min(len(links), 4))
    for idx, (code, label) in enumerate(links):
        n = len(products_for_group(item, code))
        with cols[idx % len(cols)]:
            st.button(
                f"→ {label} ({n})",
                key=f"xref_{tab_key}_{page}_{item.key}_{code}",
                use_container_width=True,
                on_click=_open_detail_with_group,
                args=(item.key, code),
            )


def render_object_card(
    item: ObjectViewItem,
    *,
    tab_key: str,
    page: int,
    on_open: Callable[[str], None] | None = None,
    active_product_group: Optional[str] = None,
) -> None:
    body = build_card_body(item, active_product_group=active_product_group)
    open_cb = on_open or (lambda k: _open_detail_with_group(k, active_product_group))

    with st.container(border=False):
        content_col, action_col = st.columns([5.2, 1])
        with content_col:
            st.markdown(body, unsafe_allow_html=True)
            _render_related_group_links(
                item,
                active_product_group=active_product_group,
                tab_key=tab_key,
                page=page,
            )
        with action_col:
            st.write("")
            st.button(
                "Открыть",
                key=stable_card_key(item.key, tab_key, page),
                use_container_width=True,
                type="primary",
                on_click=open_cb,
                args=(item.key,),
            )


def render_object_cards_batch(
    items: Sequence[ObjectViewItem],
    *,
    tab_key: str,
    page: int,
    on_open: Callable[[str], None] | None = None,
    active_product_group: Optional[str] = None,
) -> None:
    if not items:
        st.info("Нет объектов на этой странице.")
        return
    for item in items:
        render_object_card(
            item,
            tab_key=tab_key,
            page=page,
            on_open=on_open,
            active_product_group=active_product_group,
        )


def open_object_detail(object_key: str) -> None:
    _open_detail(object_key)
    st.rerun()
