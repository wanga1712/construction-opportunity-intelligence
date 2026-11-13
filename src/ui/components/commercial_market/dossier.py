"""Anchored commercial dossier renderer."""
from __future__ import annotations

from html import escape
from typing import Any, Optional

import pandas as pd
import streamlit as st

from src.services.commercial_market_read_model import money, quantity


DOSSIER_TABS = (
    "01 Сводка",
    "02 Ваши возможности",
    "03 Смета и объёмы",
    "04 Технические характеристики",
    "05 Требования к поставке",
    "06 Документы",
    "07 Заказчик / победитель",
    "08 История / модель",
)


def _line(label: str, value: Any) -> str:
    return (
        f'<div class="crm-line"><span>{escape(label)}</span>'
        f"<b>{escape(str(value if value not in (None, '') else '—'))}</b></div>"
    )


def _state(card: Optional[dict], dossier: dict) -> str:
    if card and card.get("state"):
        return str(card["state"])
    return "MATCHED" if dossier.get("opportunities") else (
        "ZERO_MATCH" if dossier.get("category_positions") else "IN_RESEARCH"
    )


def _header(card: Optional[dict], dossier: dict) -> None:
    ident = dossier.get("identity") or {}
    state = _state(card, dossier)
    medal = card.get("medal") if card else None
    state_label = f"{medal or 'MATCHED'} · {state}" if state == "MATCHED" else state.replace("_", " ")
    st.markdown(
        f"""
        <div class="crm-dossier-head">
          <div class="crm-dossier-kicker">Commercial dossier · procurement record</div>
          <div class="crm-dossier-title">{escape(str(ident.get('auction_name') or 'Досье закупки'))}</div>
          <div class="crm-dossier-sub">№ {escape(str(ident.get('contract_number') or ident.get('id') or '—'))}
            · {escape(str((dossier.get('money_and_dates') or {}).get('delivery_region') or 'регион не указан'))}</div>
          <div style="margin-top:9px"><span class="crm-dossier-state">{escape(state_label)}</span>
            <span class="crm-dossier-sub">{escape(str((card or {}).get('nmck_text') or money((dossier.get('money_and_dates') or {}).get('initial_price'))))}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _summary(card: Optional[dict], dossier: dict, tab_key: str) -> None:
    ident = dossier.get("identity") or {}
    md = dossier.get("money_and_dates") or {}
    counts = dossier.get("counts") or {}
    positions = dossier.get("category_positions") or []
    audit = dossier.get("category_position_audit") or {}
    state = _state(card, dossier)
    # The dossier/card read-model owns the displayed total. Do not manufacture
    # a second authority by summing category values in the renderer.
    material_value = (card or {}).get("material_value")
    st.markdown(
        f"""
        <div class="crm-panel-card">
          <div class="crm-panel-label">Состояние объекта</div>
          <div class="crm-kpi-row">
            <div class="crm-kpi"><b>{escape(state.replace("_", " "))}</b><span>исследование</span></div>
            <div class="crm-kpi"><b>{int(counts.get("categories") or 0)}</b><span>категории</span></div>
            <div class="crm-kpi"><b>{len(positions) if positions else int((card or {}).get("estimate_rows") or 0)}</b><span>позиции сметы</span></div>
          </div>
        </div>
        <div class="crm-panel-card">
          {_line("НМЦК", money(md.get("initial_price")))}
          {_line("Найденные материалы", money(material_value))}
          {_line("Заказчик", ident.get("customer"))}
          {_line("Начало", md.get("start_date"))}
          {_line("Окончание", md.get("end_date"))}
          {_line("Регион", md.get("delivery_region"))}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if state == "ZERO_MATCH":
        st.markdown(
            f"""
            <div class="crm-panel-card">
              <div class="crm-panel-label">Смета обработана</div>
              <div style="font-family:Georgia,serif;font-size:18px;margin-bottom:8px">
                Совпадений с текущими категориями не найдено
              </div>
              {_line("Смета", f"{len(positions)} строк")}
              {_line("Материалоподобные строки", audit.get("true_unassigned_positions", 0))}
              {_line("Полные позиции", audit.get("full_quartet_preferred", 0))}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Открыть смету", key=f"market_open_estimate_{ident.get('id')}"):
            st.session_state[tab_key] = DOSSIER_TABS[2]
            st.rerun()
    if dossier.get("errors"):
        with st.expander("Диагностика загрузки досье"):
            st.caption("; ".join(str(error) for error in dossier["errors"][:8]))


def _position_frame(
    rows: list[dict],
    categories: list[dict],
    *,
    include_taxonomy: bool = True,
) -> pd.DataFrame:
    category_names = {
        str(card.get("category_code") or ""): str(card.get("category_name") or card.get("category_code") or "—")
        for card in categories
    }
    sub_names = {
        (str(card.get("category_code") or ""), str(card.get("subcategory_code") or "")):
        str(card.get("subcategory_name") or card.get("subcategory_code") or "—")
        for card in categories
    }
    data = []
    for row in rows:
        code = str(row.get("category_code") or "")
        sub = str(row.get("subcategory_code") or "")
        item = {
            "Материал": (
                row.get("product_name_raw")
                or row.get("name_raw")
                or row.get("product_name_normalized")
                or row.get("name_normalized")
                or "—"
            ),
            "Количество": quantity(row.get("quantity") if "quantity" in row else row.get("quantity_value")),
            "Ед.": row.get("unit") or row.get("unit_normalized") or row.get("quantity_unit_normalized") or "—",
            "Цена": money(row.get("unit_price") if "unit_price" in row else row.get("unit_price_value")),
            "Сумма": money(row.get("total") if "total" in row else row.get("total_value")),
        }
        if include_taxonomy:
            item.update({
                "Категория": category_names.get(code, row.get("category_name") or code or "Без категории"),
                "Подкатегория": sub_names.get((code, sub), row.get("subcategory_name") or sub or "—"),
                "Раздел": row.get("section_name") or row.get("section_code") or "—",
            })
        data.append(item)
    return pd.DataFrame(data)


def _opportunities(dossier: dict, tab_key: str) -> None:
    cards = dossier.get("categories") or []
    if not cards:
        st.markdown(
            '<div class="crm-panel-card">Совпадений с текущими категориями не найдено. '
            'Полная смета остаётся доступной в разделе 03.</div>',
            unsafe_allow_html=True,
        )
        if st.button("Открыть смету", key=f"market_open_estimate_empty_{dossier.get('procurement_id')}"):
            st.session_state[tab_key] = DOSSIER_TABS[2]
            st.rerun()
        return
    for index, category in enumerate(cards):
        positions = category.get("positions") or []
        total = int(category.get("position_count") or len(positions))
        valued = int(category.get("value_position_count") or 0)
        missing = max(total - valued, 0)
        value = category.get("commercial_value")
        title = str(category.get("category_name") or category.get("category_code") or "Категория")
        medal = category.get("current_effective_medal") or category.get("confirmed_base_medal") or "—"
        st.markdown(
            f"""
            <div class="crm-category-card">
              <div class="crm-category-title">{escape(title)} <span class="crm-category-sub">{escape(str(medal))}</span></div>
              <div class="crm-category-sub">{escape(str(category.get("subcategory_name") or ""))}</div>
              <div class="crm-value-trace">
                <span>Стоимость категории: <b>{escape(money(value))}</b></span>
                <span>Позиции в расчёте: <b>{valued}</b></span>
                <span>Позиции без стоимости: <b>{missing}</b></span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        value_positions = category.get("value_positions") or []
        with st.expander(f"Позиции в расчёте · {valued}", expanded=index == 0):
            if value_positions:
                st.dataframe(
                    _position_frame(value_positions, cards, include_taxonomy=False),
                    use_container_width=True,
                    hide_index=True,
                    height=min(360, 38 + 30 * max(len(value_positions), 1)),
                )
            else:
                st.caption("Позиции с подтверждённой стоимостью пока отсутствуют.")
        with st.expander(f"Все позиции категории · {total}", expanded=False):
            if positions:
                st.dataframe(
                    _position_frame(positions, cards, include_taxonomy=False),
                    use_container_width=True,
                    hide_index=True,
                    height=min(420, 38 + 30 * max(len(positions), 1)),
                )
            else:
                st.caption("Для этой возможности сметные позиции пока не выделены.")


def _estimate(dossier: dict) -> None:
    rows = dossier.get("category_positions") or []
    cards = dossier.get("categories") or []
    if not rows:
        st.markdown(
            '<div class="crm-panel-card">Canonical estimate rows пока отсутствуют. '
            'Объект остаётся доступным для исследования.</div>',
            unsafe_allow_html=True,
        )
        return
    st.caption(f"Все canonical позиции сметы · {len(rows)}")
    st.dataframe(
        _position_frame(rows, cards),
        use_container_width=True,
        hide_index=True,
        height=min(680, 42 + 31 * min(len(rows), 20)),
    )
    orphan_rows = dossier.get("category_positions_without_current_opportunity") or []
    if orphan_rows:
        with st.expander(f"Назначенные позиции вне текущих возможностей · {len(orphan_rows)}"):
            st.caption("Строки сохраняют назначенную категорию и не считаются без категории.")
            st.dataframe(
                _position_frame(orphan_rows, cards),
                use_container_width=True,
                hide_index=True,
                height=min(360, 42 + 30 * min(len(orphan_rows), 10)),
            )


def _technical(dossier: dict) -> None:
    rows = [
        row for row in dossier.get("category_positions") or []
        if row.get("technical_attributes")
    ]
    if not rows:
        st.markdown(
            '<div class="crm-panel-card">Технические характеристики в смете не выделены.</div>',
            unsafe_allow_html=True,
        )
        return
    st.caption(f"Позиции с техническими признаками · {len(rows)}")
    for row in rows[:80]:
        attributes = row.get("technical_attributes") or []
        st.markdown(f"**{escape(str(row.get('product_name_raw') or 'Материал'))}**")
        st.caption(" · ".join(
            str(item.get("raw_value") or item.get("normalized_value") or item.get("attribute_name") or "")
            for item in attributes
            if isinstance(item, dict)
        ))


def _delivery(dossier: dict) -> None:
    md = dossier.get("money_and_dates") or {}
    ident = dossier.get("identity") or {}
    st.markdown(
        '<div class="crm-panel-card">'
        + _line("Регион поставки", md.get("delivery_region"))
        + _line("Адрес", md.get("delivery_address"))
        + _line("Поставка с", md.get("delivery_start_date"))
        + _line("Поставка до", md.get("delivery_end_date"))
        + _line("Обеспечение", money(md.get("guarantee_amount")))
        + _line("Гарантия", ident.get("warranty_size"))
        + _line("Площадка", ident.get("trading_platform"))
        + "</div>",
        unsafe_allow_html=True,
    )


def _documents(dossier: dict) -> None:
    documents = dossier.get("documents") or []
    if not documents:
        st.markdown('<div class="crm-panel-card">Документы ещё не материализованы.</div>',
                    unsafe_allow_html=True)
        return
    st.dataframe(
        pd.DataFrame([
            {
                "Документ": row.get("file_name") or row.get("document_name") or "—",
                "Статус": row.get("download_status") or "—",
                "Локально": "да" if row.get("has_local_file") else "нет",
                "Ссылка": "есть" if row.get("has_url") else "нет",
            }
            for row in documents
        ]),
        use_container_width=True,
        hide_index=True,
        height=min(440, 42 + 30 * min(len(documents), 13)),
    )


def _parties(dossier: dict) -> None:
    parties = dossier.get("parties") or {}
    st.markdown(
        '<div class="crm-panel-card">'
        + _line("Заказчик", parties.get("customer"))
        + _line("ИНН заказчика", parties.get("customer_inn"))
        + _line("Победитель", parties.get("winner_name"))
        + _line("ИНН победителя", parties.get("winner_inn"))
        + _line("Контрагент", parties.get("contractor_name"))
        + _line("ИНН контрагента", parties.get("contractor_inn"))
        + _line("Балансодержатель", parties.get("balance_holder"))
        + "</div>",
        unsafe_allow_html=True,
    )


def _history(dossier: dict, crm_db: Any) -> None:
    try:
        from src.services.crm_procurement_history_service import load_history, timeline_lines

        history = load_history(crm_db, int(dossier.get("procurement_id")))
        lines = timeline_lines(history)
        if lines:
            for line in lines:
                st.markdown(f"- {line}")
        else:
            st.caption("История изменений пока не сформирована.")
    except Exception as exc:
        st.caption(f"История недоступна: {type(exc).__name__}")
    with st.expander("Технические сведения"):
        st.json({
            "scope": dossier.get("scope") or {},
            "category_position_audit": dossier.get("category_position_audit") or {},
            "errors": dossier.get("errors") or [],
        })


def render_dossier(
    dossier: dict,
    crm_db: Any,
    *,
    card: Optional[dict] = None,
) -> None:
    _header(card, dossier)
    tab_key = f"market_dossier_tab_{dossier.get('procurement_id')}"
    if st.session_state.get(tab_key) not in DOSSIER_TABS:
        st.session_state[tab_key] = DOSSIER_TABS[0]
    selected = st.radio(
        "Раздел досье",
        DOSSIER_TABS,
        key=tab_key,
        horizontal=True,
        label_visibility="collapsed",
    )
    if selected == DOSSIER_TABS[0]:
        _summary(card, dossier, tab_key)
    elif selected == DOSSIER_TABS[1]:
        _opportunities(dossier, tab_key)
    elif selected == DOSSIER_TABS[2]:
        _estimate(dossier)
    elif selected == DOSSIER_TABS[3]:
        _technical(dossier)
    elif selected == DOSSIER_TABS[4]:
        _delivery(dossier)
    elif selected == DOSSIER_TABS[5]:
        _documents(dossier)
    elif selected == DOSSIER_TABS[6]:
        _parties(dossier)
    else:
        _history(dossier, crm_db)
