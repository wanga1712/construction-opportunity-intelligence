"""Card renderers for the two waterproofing funnels.

An УК card explains the account: 615-ПП history, contacts, portfolio, next touch.
An object card explains the deal: address, its УК, survey result, money, next step.

Both are built from data that already exists in the database or in the saved CRM
state, so a card never shows a placeholder figure. Money lives on the object, not
on the УК, which keeps one number from being counted twice.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import streamlit as st

from src.services.waterproofing_crm import next_touch_default, parse_date
from src.services.waterproofing_deals import merge_deal_state
from src.services.waterproofing_funnel import (
    DEAL_STAGES,
    STAGE_DEFAULT_ACTIONS,
    STAGE_LABELS,
)

OPEN_UK_KEY = "hydro_open_uk"


def _amount_text(card: dict[str, Any]) -> str:
    amount = float(card.get("potential_amount") or 0)
    if amount <= 0:
        return ""
    return str(int(amount)) if amount.is_integer() else str(amount)


def account_card_lines(card: dict[str, Any]) -> list[str]:
    """УК card: 615-ПП history, contact state, portfolio and the next touch."""
    lines = [f"**{card.get('uk_name_short')}**"]
    if card.get("tenders_615_count"):
        years = card.get("tenders_615_years") or []
        span = f"{years[0]}-{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "")
        line = f"🏗 615-ПП: {card['tenders_615_count']} торг(ов) на {card['tenders_615_amount_label']}"
        if span:
            line += f" ({span})"
        if card.get("tenders_615_year_count"):
            line += f" · в {card['tenders_615_year']}: {card['tenders_615_year_amount_label']}"
        if card.get("tenders_615_waterproofing"):
            line += f" · гидроизоляция: {card['tenders_615_waterproofing']}"
        lines.append(line)
    lines.append(f"ИНН {card.get('uk_inn')} · ☎ {card.get('phone') or '—'}")
    if card.get("uk_address"):
        lines.append(f"📍 {str(card['uk_address'])[:110]}")
    lines.append(
        f"🏢 объектов: {card.get('object_count')} · с подземными: {card.get('ge1_floors')}"
        f" · паркингов: {card.get('parking_count')}"
    )
    max_floors = int(card.get("max_underground_floors") or 0)
    floors = f"🅿 подземных этажей: {card.get('total_underground_floors')}"
    if max_floors > 1:
        floors += f" · максимум в одном паркинге: {max_floors}"
    lines.append(floors)
    lines.append(
        f"💰 {card.get('potential_amount_label')} · {card.get('priority_icon')} {card.get('priority')}"
    )
    if card.get("tech_contact"):
        lines.append(f"✅ тех. контакт: {card.get('tech_contact_person') or 'есть'}")
    else:
        lines.append("⛔ тех. контакта нет")
    touch = card.get("next_action_date") or "касание не назначено"
    if card.get("overdue"):
        touch += f" · 🔴 просрочено {card.get('overdue_days')} дн."
    lines.append(f"📅 {touch}")
    lines.append(
        f"👤 {card.get('responsible')} · 🏷 {card.get('stage_label') or card.get('stage')}"
    )
    return lines


def deal_card_lines(card: dict[str, Any]) -> list[str]:
    """Object card: address, its УК, survey, money and the next step."""
    lines = [f"**{card.get('address') or card.get('name')}**"]
    if card.get("floors_underground"):
        lines.append(f"🅿 Подземный паркинг · этажей: {card['floors_underground']}")
    lines.append(f"🏢 УК: {card.get('uk_name_short')}")
    if card.get("cadastral_number"):
        lines.append(f"КАДАСТР {card['cadastral_number']}")
    surveyed = parse_date(card.get("survey_date"))
    if surveyed:
        lines.append(f"🔍 Обследовано: {surveyed.strftime('%d.%m.%Y')}")
    lines.append(
        f"💰 {card.get('potential_amount_label')} · {card.get('priority_icon')} {card.get('priority')}"
    )
    step = card.get("next_action") or "—"
    if card.get("next_action_date"):
        step += f" до {card['next_action_date']}"
    if card.get("overdue"):
        step += f" · 🔴 просрочено {card.get('overdue_days')} дн."
    lines.append(f"📅 {step}")
    lines.append(f"👤 {card.get('responsible')}")
    return lines


def render_account_card(card: dict[str, Any]) -> None:
    """УК card with the link into the detailed account card."""
    with st.container(border=True):
        st.markdown("  \n".join(account_card_lines(card)))
        key = str(card.get("key") or "")
        if st.button("Открыть карточку УК", key=f"hydro_open_{key}", use_container_width=True):
            st.session_state[OPEN_UK_KEY] = key
            st.rerun()


def _deal_progress_form(card: dict[str, Any]) -> None:
    """Record progress on one object: stage, next step, money, survey date."""
    key = str(card.get("key") or "")
    stage_ids = [stage.id for stage in DEAL_STAGES]
    current = str(card.get("stage") or stage_ids[0])
    index = stage_ids.index(current) if current in stage_ids else 0
    with st.expander("Этап и следующий шаг"):
        stage = st.selectbox(
            "Этап",
            stage_ids,
            index=index,
            format_func=lambda value: STAGE_LABELS.get(value, value),
            key=f"deal_stage_{key}",
        )
        next_action = st.text_input(
            "Следующее действие",
            value=str(card.get("next_action") or STAGE_DEFAULT_ACTIONS.get(stage, "")),
            key=f"deal_next_{key}",
        )
        planned = st.date_input(
            "Дата следующего шага",
            value=parse_date(card.get("next_action_date"))
            or parse_date(next_touch_default(stage))
            or date.today(),
            key=f"deal_date_{key}",
        )
        amount = st.text_input(
            "Потенциал",
            value=_amount_text(card),
            placeholder="например 2,4 млн",
            key=f"deal_amount_{key}",
        )
        surveyed = st.date_input(
            "Дата обследования",
            value=parse_date(card.get("survey_date")) or date.today(),
            key=f"deal_survey_{key}",
        )
        responsible = st.text_input(
            "Ответственный", value="" if card.get("responsible") == "—" else str(card.get("responsible") or ""),
            key=f"deal_resp_{key}",
        )
        if st.button("Сохранить", key=f"deal_save_{key}", type="primary"):
            merge_deal_state(key, {
                "stage": stage,
                "next_action": next_action,
                "next_action_date": planned.isoformat(),
                "potential_amount": amount,
                "survey_date": surveyed.isoformat(),
                "responsible": responsible,
                "address": card.get("address") or "",
                "cadastral_number": card.get("cadastral_number") or "",
                "uk_key": card.get("uk_key") or "",
                "uk_name": card.get("uk_name") or "",
            })
            st.success("Объект обновлён.")
            st.rerun()


def render_deal_card(card: dict[str, Any]) -> None:
    """Object card with the progress form for that object."""
    with st.container(border=True):
        st.markdown("  \n".join(deal_card_lines(card)))
        _deal_progress_form(card)


__all__ = [
    "OPEN_UK_KEY",
    "account_card_lines",
    "deal_card_lines",
    "render_account_card",
    "render_deal_card",
]
