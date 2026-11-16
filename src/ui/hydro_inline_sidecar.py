"""Compact, tabbed manager workspace rendered in the Kanban overlay."""
from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Any, Callable

import streamlit as st

from src.services.hydro.company_repository import HydroCompanyRepository
from src.services.waterproofing_crm import CRM_STAGES
from src.ui.hydro_inline_workspace_tabs import (
    dispatch_workspace_tab,
    render_615,
    render_actions,
    render_contacts,
    render_objects,
)

SIDECAR_OPEN_KEY = "hydro_inline_sidecar_open"
SIDECAR_SELECTED_KEY = "hydro_inline_sidecar_selected"
TAB_KEY = "hydro_inline_workspace_tab"


def _company_row(repo: HydroCompanyRepository, inn: Any) -> dict[str, Any] | None:
    try:
        return repo.get_by_inn(inn)
    except Exception:
        return None


def _objects_for(object_rows: list[dict[str, Any]], inn: Any) -> list[dict[str, Any]]:
    target = str(inn or "")
    return [row for row in object_rows if str(row.get("uk_inn") or "") == target]


def _website_link(value: Any) -> str:
    website = str(value or "").strip()
    if not website:
        return "Сайт не указан"
    url = website if website.startswith(("https://", "http://")) else f"https://{website}"
    if not url.startswith(("https://", "http://")):
        return "Сайт не указан"
    safe_url = html.escape(url, quote=True)
    return f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">Сайт ↗</a>'


def _metric_summary(company: Mapping[str, Any], objects: list[dict[str, Any]], card: Mapping[str, Any]) -> str:
    object_count = int(company.get("objects_count") or len(objects))
    parking_count = int(card.get("parking_count") or sum(int(row.get("parking_spaces") or 0) for row in objects))
    floor_count = int(card.get("total_underground_floors") or sum(int(row.get("floors_underground") or 0) for row in objects))
    parts = [f"{object_count} объектов"]
    if object_count:
        parts.append(f"{parking_count} паркингов")
        parts.append(f"{floor_count} подземных этажей")
    priority = card.get("medal_label") or card.get("medal") or card.get("medal_name") or card.get("priority")
    if priority:
        parts.append(str(priority))
    return " · ".join(parts)


def _six_fifteen_count(card: Mapping[str, Any]) -> int:
    for key in ("tenders_615_count", "history_tenders_615", "contracts_615_count"):
        try:
            if card.get(key) is not None:
                return int(card[key])
        except (TypeError, ValueError):
            pass
    summary = card.get("tenders_615") or card.get("waterproofing_615") or {}
    if isinstance(summary, Mapping):
        for key in ("history_tenders", "tenders", "contracts", "contracts_count"):
            try:
                if summary.get(key) is not None:
                    return int(summary[key])
            except (TypeError, ValueError):
                pass
    return 0


def render_inline_sidecar(
    card: Mapping[str, Any],
    crm_db: Any,
    object_rows: list[dict[str, Any]],
    move_stage: Callable[[str], Mapping[str, Any]],
) -> None:
    """Show the full manager workspace without navigating away from Kanban."""
    if not st.session_state.get(SIDECAR_OPEN_KEY):
        return
    selected_key = str(card.get("key") or "")
    inn = card.get("uk_inn")
    name = str(card.get("uk_name") or card.get("uk_name_short") or "Управляющая компания")
    repo = HydroCompanyRepository(crm_db) if crm_db else None
    company = _company_row(repo, inn) if repo else None
    objects = _objects_for(object_rows, inn)

    with st.container(key="hydro_inline_sidecar"):
        title_col, close_col = st.columns([12, 1], vertical_alignment="center")
        with title_col:
            phone = (company or {}).get("phone") or card.get("phone") or "Телефон не указан"
            website = _website_link((company or {}).get("website"))
            st.markdown(
                f"### {html.escape(name)}\n\n"
                f"ИНН {html.escape(str(inn or '—'))} · {html.escape(str(phone))} · {website}",
                unsafe_allow_html=True,
            )
            if company:
                st.caption(_metric_summary(company, objects, card))
            stage = str(card.get("stage") or "")
            stage_label = stage if stage in CRM_STAGES else card.get("stage_label") or stage or "—"
            next_step = str(card.get("next_action") or "Следующий шаг не задан")
            st.markdown(f"**Этап:** {stage_label}　 **Следующий шаг:** {next_step}")
        with close_col:
            if st.button("×", key="hydro_inline_sidecar_close", help="Закрыть рабочее пространство"):
                st.session_state[SIDECAR_SELECTED_KEY] = None
                st.session_state[SIDECAR_OPEN_KEY] = False
                st.rerun()

        if not company or not repo:
            st.info("Карточка УК отсутствует в CRM. Для контактов, объектов и действий нужна запись management_companies.")
            return

        contract_count = _six_fifteen_count(card)
        labels = ["Контакты", f"Объекты · {int(company.get('objects_count') or len(objects))}",
                  f"615-ПП · {contract_count}", "Действия"]
        if hasattr(st, "segmented_control"):
            selected = st.segmented_control(
                "Рабочие разделы", labels, default=labels[0],
                label_visibility="collapsed", key=TAB_KEY,
            )
        else:
            selected = st.radio(
                "Рабочие разделы", labels, horizontal=True,
                label_visibility="collapsed", key=TAB_KEY,
            )
        selected = selected or labels[0]
        dispatch_workspace_tab(selected, labels, {
            labels[0]: lambda: render_contacts(repo, company, card),
            labels[1]: lambda: render_objects(repo, company, str(card.get("key") or "")),
            labels[2]: lambda: render_615(repo, company, str(card.get("key") or "")),
            labels[3]: lambda: render_actions(repo, company, card, move_stage),
        })


__all__ = ["SIDECAR_OPEN_KEY", "SIDECAR_SELECTED_KEY", "render_inline_sidecar"]
