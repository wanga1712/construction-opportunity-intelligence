"""Waterproofing CRM board: the УК funnel and the object funnel.

The unit of work changes inside this direction, so the section runs two linked
funnels instead of one long board:

* Until a concrete address exists the card is the managing company — find the УК,
  reach the decision maker, hold the meeting, get the objects and the access.
* Once an object exists the card is that object — survey, proposal,
  specification, procurement, contract.

One УК therefore appears on the УК board exactly once, while its objects progress
independently on the object board. Micro-actions such as a first call or a found
chief engineer are not columns: they live in activity, history and next action.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from src.services.hydro_daily_sync import read_health
from src.services.map_export import fetch_uk_object_addresses, fetch_uk_summary
from src.services.objects_service import ObjectsService
from src.services.waterproofing_615_store import board_615_line, read_board
from src.services.waterproofing_board import (
    account_columns,
    apply_filters,
    dashboard_kpis,
    uk_district,
    uk_districts,
)
from src.services.waterproofing_contour import (
    contour_key,
    load_contour_states,
    merge_contour_state,
)
from src.services.waterproofing_crm import (
    CRM_STAGES,
    STAGE_DEFAULT_ACTIONS,
    board_kpis,
    build_card,
    next_touch_default,
)
from src.services.waterproofing_deals import (
    build_deal_card,
    deal_columns,
    deal_key,
    load_deal_states,
)
from src.services.waterproofing_funnel import (
    ACCOUNT_STAGES,
    DEAL_STAGES,
    FUNNEL_ACCOUNT,
    FUNNEL_DEAL,
    normalize_stage,
)
from src.services.waterproofing_stage_move import (
    INVALID_FUNNEL,
    INVALID_STAGE,
    STALE_STAGE_MOVE,
    move_card_stage,
)
from src.ui.components.hydro_drag_drop import hydro_drag_drop
from src.ui.hydro_board import (
    BAND_ACCOUNT,
    BAND_DEAL,
    render_band,
    render_board,
    render_kpi_strip,
)
from src.ui.hydro_cards import (
    SIDECAR_OPEN_KEY,
    SIDECAR_SELECTED_KEY,
    call_calendar_rows,
    render_account_card,
    render_deal_card,
)
from src.ui.hydro_dom import kanban_card_key, kanban_column_key
from src.ui.hydro_filters import render_toolbar
from src.ui.hydro_inline_sidecar import render_inline_sidecar
from src.ui.session_deps import get_parking_db

SEARCH_ACCOUNT = ("uk_name", "uk_name_short", "uk_inn", "uk_ogrn", "uk_address")
SEARCH_DEAL = ("name", "address", "cadastral_number", "uk_name", "uk_name_short")
BASE_LIMIT = 50
INTAKE_KEY = "hydro_intake_open"
ACCOUNT_BOARD_KEY = "hydro_board_account"
DEAL_BOARD_KEY = "hydro_board_deal"
DRAG_EVENT_KEY = "hydro_kanban_last_drag_event"
DRAG_NOTICE_KEY = "hydro_kanban_drag_notice"


def _load_615(service: Any) -> dict[str, Any]:
    """Готовый срез 615-ПП из CRM БД: связка считается раз в сутки, не в UI."""
    return read_board(getattr(service, "crm_db", None))


def _data_line(service: Any, snapshot: dict[str, Any]) -> str:
    """Freshness of the daily loads. Never reports a missing load as zero."""
    state = snapshot.get("state") or {}
    if state.get("last_success_at"):
        parts = [f"615-ПП: связка обновлена {str(state['last_success_at'])[:10]}"]
    else:
        parts = ["615-ПП: связка ещё не рассчитана"]
    health = read_health(getattr(service, "crm_db", None))
    if health.get("last_success_at"):
        parts.append(
            f"Hydro: загрузка {str(health['last_success_at'])[:10]} "
            f"(+{int(health.get('rows_inserted') or 0)} / ~"
            f"{int(health.get('rows_updated') or 0)})"
        )
    elif health.get("status"):
        parts.append(f"Hydro: загрузка — {str(health['status']).lower()}")
    else:
        parts.append("Hydro: ежедневная загрузка ещё не запускалась")
    return " · ".join(parts)


def _account_cards(
    states: dict[str, dict[str, Any]],
    uk_rows: list[dict[str, Any]],
    tenders_by_key: dict[str, Any],
) -> list[dict[str, Any]]:
    """Contours in work first, then every УК of the base as «Новая УК / База»."""
    rows_by_key = {contour_key(row): row for row in uk_rows}
    cards = [
        build_card(rows_by_key.get(key, {}), state, tenders_615=tenders_by_key.get(key))
        for key, state in states.items()
    ]
    cards += [
        build_card(row, tenders_615=tenders_by_key.get(contour_key(row)))
        for row in uk_rows
        if contour_key(row) not in states
    ]
    return cards


def _deal_cards(
    account_cards: list[dict[str, Any]],
    object_rows: list[dict[str, Any]],
    deal_states: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Objects enter the deal funnel once access is granted or work has started."""
    granted = {
        str(card.get("key") or "")
        for card in account_cards
        if normalize_stage(card.get("stage")) == "survey_approved"
    }
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in object_rows:
        object_row = {
            "object_id": row.get("object_id"),
            "name": row.get("address_text"),
            "address": row.get("address_text"),
            "cadastral_number": row.get("cadastral_number"),
            "floors_underground": row.get("floors_underground"),
        }
        key = deal_key(object_row)
        if not key or key in seen:
            continue
        state = deal_states.get(key)
        if state is None and contour_key(row) not in granted:
            continue
        seen.add(key)
        cards.append(build_deal_card(object_row, row, state))
    return cards


def _cap_base_column(columns: list[dict[str, Any]]) -> None:
    """Keep the «База» column usable without hiding how many УК it holds."""
    for column in columns:
        if column.get("stage") != FUNNEL_ACCOUNT or column.get("index") != 0:
            continue
        cards = column.get("cards") or []
        if len(cards) > BASE_LIMIT:
            column["hidden"] = len(cards) - BASE_LIMIT
            column["cards"] = cards[:BASE_LIMIT]


def _consume_drag_event(event: dict[str, Any]) -> None:
    """Validate and persist one structured drop event."""
    if event.get("type") != "hydro_stage_move":
        return
    event_id = str(event.get("event_id") or "")
    if not event_id or event_id == st.session_state.get(DRAG_EVENT_KEY):
        return
    result = move_card_stage(
        card_key=str(event.get("card_key") or ""),
        funnel=str(event.get("funnel") or ""),
        from_stage=str(event.get("from_stage") or ""),
        to_stage=str(event.get("to_stage") or ""),
    )
    st.session_state[DRAG_EVENT_KEY] = event_id
    reason = str(result.get("reason") or "")
    if reason == STALE_STAGE_MOVE:
        st.session_state[DRAG_NOTICE_KEY] = (
            "Этап уже был изменён в другой вкладке. Доска обновлена без перезаписи."
        )
    elif reason in (INVALID_FUNNEL, INVALID_STAGE):
        st.session_state[DRAG_NOTICE_KEY] = (
            "Перемещение отклонено: этап не относится к этой воронке."
        )
    st.rerun()


def _render_drag_and_drop(
    account_cards: list[dict[str, Any]],
    deal_cards: list[dict[str, Any]],
    *,
    selected_account_key: str | None = None,
    sidecar_open: bool = False,
) -> None:
    """Attach one drag-drop bridge to both rendered funnels."""
    cards = [
        {
            "dom_key": kanban_card_key(funnel, card.get("key")),
            "card_key": str(card.get("key") or ""),
            "stage": str(card.get("stage") or ""),
            "funnel": funnel,
            "open_sidecar": funnel == FUNNEL_ACCOUNT,
        }
        for funnel, rows in (
            (FUNNEL_ACCOUNT, account_cards),
            (FUNNEL_DEAL, deal_cards),
        )
        for card in rows
    ]
    columns = [
        {
            "dom_key": kanban_column_key(board_key, stage.id),
            "stage": stage.id,
            "funnel": funnel,
        }
        for funnel, board_key, stages in (
            (FUNNEL_ACCOUNT, ACCOUNT_BOARD_KEY, ACCOUNT_STAGES),
            (FUNNEL_DEAL, DEAL_BOARD_KEY, DEAL_STAGES),
        )
        for stage in stages
    ]
    selected_dom_key = None
    if selected_account_key:
        selected_dom_key = kanban_card_key("account", selected_account_key)
    event = hydro_drag_drop(
        cards=cards,
        columns=columns,
        key="hydro_kanban_drag",
        selected_account_dom_key=selected_dom_key,
        sidecar_open=sidecar_open,
    )
    if isinstance(event, dict):
        _consume_drag_event(event)


def _render_call_calendar(cards: list[dict[str, Any]]) -> None:
    """Agenda view; equal time slots remain separate rows for each UK."""
    rows = call_calendar_rows(cards)
    with st.expander(f"📅 Календарь звонков ({len(rows)})"):
        if not rows:
            st.caption("Звонки не запланированы: заполните дату и время касания в карточке УК.")
            return
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Дата": st.column_config.TextColumn("Дата", width="small"),
                "Время": st.column_config.TextColumn("Время", width="small"),
                "УК": st.column_config.TextColumn("УК", width="large"),
                "Цель звонка": st.column_config.TextColumn("Цель звонка", width="large"),
                "Часы приёма": st.column_config.TextColumn("Часы приёма", width="medium"),
            },
        )
        st.caption("Одинаковое время у разных УК показывается отдельными строками.")


def _render_actions(service: Any, snapshot: dict[str, Any]) -> None:
    """Header action row: data freshness on the left, the two actions on the right."""
    left, add, refresh = st.columns([4, 1, 1], vertical_alignment="bottom")
    with left:
        st.caption(_data_line(service, snapshot))
    with add:
        if st.button("+ Добавить УК", key="hydro_add_uk", use_container_width=True):
            st.session_state[INTAKE_KEY] = True
            st.rerun()
    with refresh:
        if st.button("Обновить", key="hydro_refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()


def _render_intake(uk_rows: list[dict[str, Any]], states: dict[str, dict[str, Any]]) -> None:
    """Take an УК from the source base into work without leaving the board."""
    free_rows = [row for row in uk_rows if contour_key(row) not in states]
    with st.expander(f"Добавить УК из базы в работу ({len(free_rows)})", key=INTAKE_KEY):
        if not free_rows:
            st.caption("Все УК из выбранного среза уже взяты в работу.")
            return
        responsible = st.text_input("Ответственный для новых УК", key="hydro_intake_responsible")
        stage = CRM_STAGES[0]
        ordered = sorted(
            free_rows, key=lambda row: int(row.get("total_underground_floors") or 0), reverse=True
        )
        for row in ordered[:20]:
            key = contour_key(row)
            left, right = st.columns([4, 1])
            left.markdown(
                f"**{row.get('uk_name')}** · объектов: {row.get('object_count')} · "
                f"паркингов: {row.get('parking_count')} · "
                f"подземных этажей: {row.get('total_underground_floors')} · "
                f"☎ {row.get('uk_phone') or '—'}"
            )
            if right.button("В работу", key=f"hydro_intake_{key}", use_container_width=True):
                merge_contour_state(key, {
                    "uk_name": row.get("uk_name"), "uk_inn": row.get("uk_inn"),
                    "uk_ogrn": row.get("uk_ogrn"), "uk_phone": row.get("uk_phone"),
                    "uk_address": row.get("uk_address"),
                    "object_count": int(row.get("object_count") or 0),
                    "parking_count": int(row.get("parking_count") or 0),
                    "total_underground_floors": int(row.get("total_underground_floors") or 0),
                    "max_underground_floors": int(row.get("max_underground_floors") or 0),
                    "ge1_floors": int(row.get("ge1_floors") or 0),
                    "ge2_floors": int(row.get("ge2_floors") or 0),
                    "stage": stage, "next_action": STAGE_DEFAULT_ACTIONS[stage],
                    "next_action_date": next_touch_default(stage),
                    "responsible": responsible,
                })
                st.session_state[INTAKE_KEY] = False
                st.success(f"{row.get('uk_name')} добавлена в воронку.")
                st.rerun()


def render_kanban_tab(service: ObjectsService) -> None:
    """Render the two linked boards of the waterproofing CRM."""
    parking_db = get_parking_db()
    db_ok = bool(parking_db.connect())
    if not db_ok:
        st.warning(
            f"База объектов недоступна ({parking_db.last_error}); "
            "показаны только УК, взятые в работу."
        )
    snapshot_615 = _load_615(service)
    tenders_by_key = dict(snapshot_615.get("uk") or {})
    states = load_contour_states()
    uk_rows = fetch_uk_summary(parking_db, min_floors=1) if db_ok else []
    account_cards = _account_cards(states, uk_rows, tenders_by_key)

    object_rows = fetch_uk_object_addresses(parking_db, min_floors=0) if db_ok else []
    deal_cards = _deal_cards(account_cards, object_rows, load_deal_states())

    _render_actions(service, snapshot_615)
    render_kpi_strip(dashboard_kpis(account_cards, deal_cards))
    all_kpis = board_kpis(account_cards)
    line = board_615_line(snapshot_615, all_kpis)
    if line["level"] == "warning":
        st.warning(line["text"])
    else:
        st.caption(line["text"])
    st.caption(
        f"ГБУ «Жилищник» на доске: {all_kpis['municipal']} · "
        f"с тех. контактом: {all_kpis['with_tech_contact']}"
    )

    filters = render_toolbar(
        districts=sorted({*uk_districts(account_cards), *uk_districts(deal_cards)}),
        managers=sorted({
            str(card.get("responsible"))
            for card in [*account_cards, *deal_cards]
            if card.get("responsible") not in (None, "", "—")
        }),
    )
    visible_accounts = apply_filters(
        account_cards,
        filters,
        district_of=uk_district,
        active_of=lambda card: int(card.get("object_count") or 0) > 0,
        search_fields=SEARCH_ACCOUNT,
    )
    visible_deals = apply_filters(
        deal_cards,
        filters,
        district_of=uk_district,
        active_of=lambda card: bool(card.get("in_work")),
        search_fields=SEARCH_DEAL,
    )

    if db_ok:
        _render_intake(uk_rows, states)

    drag_notice = st.session_state.pop(DRAG_NOTICE_KEY, None)
    if drag_notice:
        st.warning(str(drag_notice))
    st.caption("Перетащите карточку в колонку нужного этапа.")
    _render_call_calendar(visible_accounts)
    account_columns_rows = account_columns(visible_accounts)
    _cap_base_column(account_columns_rows)
    render_band(*BAND_ACCOUNT)
    render_board(account_columns_rows, render_account_card, key=ACCOUNT_BOARD_KEY)

    st.caption(
        "Объекты без адреса или координат в воронку объектов не попадают: "
        "их нельзя ни обследовать, ни сопоставить с торгами."
    )
    render_band(*BAND_DEAL)
    render_board(deal_columns(visible_deals), render_deal_card, key=DEAL_BOARD_KEY)
    selected_key = st.session_state.get(SIDECAR_SELECTED_KEY)
    sidecar_open = bool(st.session_state.get(SIDECAR_OPEN_KEY) and selected_key)
    selected_card = next(
        (card for card in visible_accounts if str(card.get("key") or "") == str(selected_key or "")),
        None,
    )
    if sidecar_open and selected_card:
        render_inline_sidecar(
            selected_card,
            getattr(service, "crm_db", None),
            object_rows,
            move_stage=lambda target: move_card_stage(
                card_key=str(selected_card.get("key") or ""),
                funnel=FUNNEL_ACCOUNT,
                from_stage=str(selected_card.get("stage") or ""),
                to_stage=str(target),
            ),
        )
    elif sidecar_open:
        st.session_state[SIDECAR_SELECTED_KEY] = None
        st.session_state[SIDECAR_OPEN_KEY] = False
        sidecar_open = False
    _render_drag_and_drop(
        account_cards,
        deal_cards,
        selected_account_key=str(selected_key) if sidecar_open else None,
        sidecar_open=sidecar_open,
    )
