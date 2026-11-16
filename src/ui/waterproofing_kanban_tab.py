"""UK kanban board — the main screen of the waterproofing CRM."""
from __future__ import annotations

from hashlib import sha1
from typing import Any

import streamlit as st

from src.services.map_export import fetch_uk_object_addresses, fetch_uk_summary
from src.services.objects_service import ObjectsService
from src.services.waterproofing_615_store import board_615_line, read_board
from src.services.waterproofing_contour import (
    contour_key,
    latest_contour_state,
    load_contour_states,
    merge_contour_state,
)
from src.services.waterproofing_crm import (
    CRM_STAGES,
    normalize_stage,
    PRIORITIES,
    STAGE_DEFAULT_ACTIONS,
    board_kpis,
    build_card,
    kanban_columns,
    next_touch_default,
)
from src.ui.components.hydro_drag_drop import hydro_drag_drop
from src.ui.hydro_inline_sidecar import (
    SIDECAR_OPEN_KEY,
    SIDECAR_SELECTED_KEY,
    render_inline_sidecar,
)
from src.ui.session_deps import get_parking_db

COLUMNS_PER_ROW = 6
SCOPE_WORK = "УК в работе"
SCOPE_ALL = "Все УК из базы"
DRAG_EVENT_KEY = "hydro_remote_last_drag_event"
DRAG_NOTICE_KEY = "hydro_remote_drag_notice"


def _load_615(service: Any) -> dict[str, Any]:
    """Готовый срез 615-ПП из CRM БД: связка считается раз в сутки, не в UI.

    Доска не обращается к источнику торгов и не делает нечёткое сопоставление
    на каждый rerun. Если хранилище пустое или устарело, это видно в подписи,
    а не превращается в «0 торгов».
    """
    return read_board(getattr(service, "crm_db", None))


def _move_overlay_stage(card: dict[str, Any], target: str) -> dict[str, Any]:
    """Persist an inline stage move while inheriting the full contour journal row."""
    key = str(card.get("key") or "")
    current = normalize_stage(card.get("stage"))
    actual = normalize_stage(latest_contour_state(key).get("stage"))
    if target not in CRM_STAGES:
        return {"moved": False, "reason": "INVALID_STAGE"}
    if actual != current:
        return {"moved": False, "reason": "STALE_STAGE_MOVE", "actual_stage": actual}
    if target == current:
        return {"moved": False, "reason": "NOOP"}
    merge_contour_state(key, {
        "stage": target,
        "next_action": STAGE_DEFAULT_ACTIONS.get(target, ""),
        "next_action_date": next_touch_default(target),
    })
    return {"moved": True, "from_stage": current, "to_stage": target}


def _render_kpis(cards: list[dict[str, Any]], snapshot: dict[str, Any] | None = None) -> None:
    kpis = board_kpis(cards)
    columns = st.columns(6)
    for column, label, value in zip(columns, (
        "УК на доске", "Объектов", "Паркингов", "Подземных этажей", "Просрочено", "Потенциал",
    ), (
        kpis["contours"], kpis["objects"], kpis["parkings"],
        kpis["underground_floors"], kpis["overdue"], kpis["amount_label"],
    )):
        column.metric(label, value)
    line = board_615_line(snapshot or {}, kpis)
    if line["level"] == "warning":
        st.warning(line["text"])
    else:
        st.caption(line["text"])
    st.caption(
        f"ГБУ «Жилищник» на доске: {kpis['municipal']} · "
        f"с тех. контактом: {kpis['with_tech_contact']}"
    )
    if kpis["overdue"]:
        st.warning(f"Просрочено касаний: {kpis['overdue']}. Начните с красных карточек.")


def _call_readiness(card: dict[str, Any]) -> dict[str, Any]:
    checks = (
        ("телефон", bool(str(card.get("phone") or "").strip())),
        ("часы приёма", bool(str(card.get("reception_hours") or "").strip())),
        ("ответственный", str(card.get("responsible") or "").strip() not in ("", "—")),
        ("следующее действие", bool(str(card.get("next_action") or "").strip())),
        ("дата касания", bool(str(card.get("next_action_date") or "").strip())),
        ("время звонка", bool(str(card.get("next_action_time") or "").strip())),
    )
    missing = [label for label, present in checks if not present]
    goal = str(
        card.get("next_action")
        or STAGE_DEFAULT_ACTIONS.get(str(card.get("stage") or ""), "")
    ).strip()
    return {"ready": not missing, "missing": missing, "goal": goal}


def _card_lines(card: dict[str, Any]) -> list[str]:
    """Поля карточки УК на канбане: без ОГРН и без подсказки «следующее действие»."""
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
    lines.append(f"💰 {card.get('potential_amount_label')} · {card.get('priority_icon')} {card.get('priority')}")
    if card.get("tech_contact"):
        lines.append(f"✅ тех. контакт: {card.get('tech_contact_person') or 'есть'}")
    else:
        lines.append("⛔ тех. контакта нет")
    reception = str(card.get("reception_hours") or "").strip()
    lines.append(f"🕘 приём: {reception or 'не указаны'}")
    touch = " ".join(
        part for part in (
            str(card.get("next_action_date") or "").strip(),
            str(card.get("next_action_time") or "").strip(),
        )
        if part
    ) or "касание не назначено"
    if card.get("overdue"):
        touch += f" · 🔴 просрочено {card.get('overdue_days')} дн."
    lines.append(f"📅 {touch}")
    lines.append(f"👤 {card.get('responsible')} · 🏷 {card.get('stage')}")
    readiness = _call_readiness(card)
    if readiness["ready"]:
        lines.append(f"✅ К звонку готово · 🎯 {readiness['goal']}")
    else:
        lines.append(f"⚠️ Заполнить перед звонком: {', '.join(readiness['missing'])}")
        if readiness["goal"]:
            lines.append(f"🎯 Цель звонка: {readiness['goal']}")
    return lines


def _card_dom_key(card_key: Any) -> str:
    digest = sha1(str(card_key or "").encode("utf-8")).hexdigest()[:16]
    return f"hydro_remote_card_{digest}"


def _column_dom_key(index: int) -> str:
    return f"hydro_remote_column_{int(index)}"


def _render_card(card: dict[str, Any]) -> None:
    key = str(card.get("key") or "")
    with st.container(key=_card_dom_key(key)):
        if st.button(
            "  \n".join(_card_lines(card)),
            key=f"hydro_select_account_{key}",
            use_container_width=True,
            type="secondary",
        ):
            st.session_state[SIDECAR_SELECTED_KEY] = key
            st.session_state[SIDECAR_OPEN_KEY] = True
            st.rerun()
        st.markdown(
            '<span class="hydro-drag-handle" draggable="true" '
            'title="Перетащить карточку" aria-label="Перетащить карточку">⠿</span>',
            unsafe_allow_html=True,
        )


def _render_column(column: dict[str, Any]) -> None:
    with st.container(border=True, key=_column_dom_key(column["index"])):
        st.markdown(f"**{column['index'] + 1}. {column['stage']}**")
        st.caption(f"{column['count']} УК · {column['amount_label']}")
        if not column["cards"]:
            st.caption("— пусто —")
        for card in column["cards"]:
            _render_card(card)


def _consume_drag_event(event: dict[str, Any], cards: list[dict[str, Any]]) -> None:
    """Persist one validated S13 board drop into the existing contour journal."""
    if event.get("type") != "hydro_stage_move":
        return
    event_id = str(event.get("event_id") or "")
    if not event_id or event_id == st.session_state.get(DRAG_EVENT_KEY):
        return
    card_key = str(event.get("card_key") or "")
    funnel = str(event.get("funnel") or "")
    from_stage = str(event.get("from_stage") or "")
    to_stage = str(event.get("to_stage") or "")
    card = next((row for row in cards if str(row.get("key") or "") == card_key), None)
    if funnel != "account" or card is None or from_stage not in CRM_STAGES or to_stage not in CRM_STAGES:
        st.session_state[DRAG_NOTICE_KEY] = "Перемещение отклонено: неверная воронка или этап."
        st.session_state[DRAG_EVENT_KEY] = event_id
        st.rerun()
    actual_stage = str(latest_contour_state(card_key).get("stage") or CRM_STAGES[0])
    if actual_stage != from_stage:
        st.session_state[DRAG_NOTICE_KEY] = (
            "Этап уже был изменён в другой вкладке. Доска обновлена без перезаписи."
        )
        st.session_state[DRAG_EVENT_KEY] = event_id
        st.rerun()
    if from_stage != to_stage:
        merge_contour_state(card_key, {
            "uk_name": card.get("uk_name") or "",
            "uk_inn": card.get("uk_inn") or "",
            "uk_ogrn": card.get("uk_ogrn") or "",
            "uk_phone": card.get("uk_phone") or "",
            "uk_address": card.get("uk_address") or "",
            "object_count": int(card.get("object_count") or 0),
            "parking_count": int(card.get("parking_count") or 0),
            "total_underground_floors": int(card.get("total_underground_floors") or 0),
            "max_underground_floors": int(card.get("max_underground_floors") or 0),
            "ge1_floors": int(card.get("ge1_floors") or 0),
            "ge2_floors": int(card.get("ge2_floors") or 0),
            "stage": to_stage,
            "next_action": STAGE_DEFAULT_ACTIONS[to_stage],
            "next_action_date": next_touch_default(to_stage),
        })
    st.session_state[DRAG_EVENT_KEY] = event_id
    st.rerun()


def _render_drag_and_drop(
    cards: list[dict[str, Any]], columns: list[dict[str, Any]], *,
    selected_account_key: str | None = None, sidecar_open: bool = False,
) -> None:
    selected_dom_key = _card_dom_key(selected_account_key) if selected_account_key else None
    event = hydro_drag_drop(
        cards=[{
            "dom_key": _card_dom_key(card.get("key")),
            "card_key": str(card.get("key") or ""),
            "stage": str(card.get("stage") or ""),
            "funnel": "account",
            "open_sidecar": True,
        } for card in cards],
        columns=[{
            "dom_key": _column_dom_key(column["index"]),
            "stage": str(column["stage"]),
            "funnel": "account",
        } for column in columns],
        key="hydro_remote_drag",
        selected_account_dom_key=selected_dom_key,
        sidecar_open=sidecar_open,
    )
    if isinstance(event, dict):
        _consume_drag_event(event, cards)


def _render_board(
    cards: list[dict[str, Any]], all_cards: list[dict[str, Any]], *,
    selected_account_key: str | None = None, sidecar_open: bool = False,
) -> None:
    columns = kanban_columns(cards)
    for start in range(0, len(columns), COLUMNS_PER_ROW):
        row = columns[start:start + COLUMNS_PER_ROW]
        for column, cell in zip(st.columns(len(row)), row):
            with column:
                _render_column(cell)
    _render_drag_and_drop(
        all_cards, columns,
        selected_account_key=selected_account_key,
        sidecar_open=sidecar_open,
    )


def _render_intake(uk_rows: list[dict[str, Any]], states: dict[str, dict[str, Any]]) -> None:
    free_rows = [row for row in uk_rows if contour_key(row) not in states]
    with st.expander(f"➕ Взять УК из базы в работу ({len(free_rows)})"):
        if not free_rows:
            st.caption("Все УК из выбранного среза уже взяты в работу.")
            return
        responsible = st.text_input("Ответственный для новых контуров", key="hydro_intake_responsible")
        stage = CRM_STAGES[0]
        ordered = sorted(free_rows, key=lambda r: int(r.get("total_underground_floors") or 0), reverse=True)
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
                st.success(f"{row.get('uk_name')} добавлена в воронку.")
                st.rerun()


def _render_filters(cards: list[dict[str, Any]], *, db_ok: bool, has_work: bool) -> dict[str, Any]:
    c1, c2, c3, c4 = st.columns([1, 1, 2, 1])
    with c1:
        min_floors = st.selectbox(
            "Подземные этажи", [1, 2, 3, 0], index=0,
            format_func=lambda value: "Любые" if value == 0 else f"≥ {value}",
            key="hydro_board_min_floors",
        )
    with c2:
        priority = st.selectbox("Приоритет", ("Все",) + PRIORITIES, index=0, key="hydro_board_priority")
    with c3:
        query = st.text_input("Поиск УК / ИНН / адрес", key="hydro_board_query").strip().lower()
    with c4:
        only_overdue = st.toggle("Только просрочка", key="hydro_board_overdue")
    scope_options = [SCOPE_WORK, SCOPE_ALL] if db_ok else [SCOPE_WORK]
    if db_ok and not has_work and "hydro_board_scope" not in st.session_state:
        st.session_state["hydro_board_scope"] = SCOPE_ALL
    scope = st.radio("Срез доски", scope_options, horizontal=True, key="hydro_board_scope")
    left, right = st.columns([2, 1])
    with left:
        responsibles = sorted({str(card.get("responsible")) for card in cards if card.get("responsible") != "—"})
        responsible = st.selectbox(
            "Ответственный", ("Все",) + tuple(responsibles), index=0, key="hydro_board_responsible"
        )
    with right:
        municipal_only = st.toggle("Только ГБУ «Жилищник»", key="hydro_board_municipal")
    return {
        "min_floors": min_floors, "priority": priority, "query": query, "only_overdue": only_overdue,
        "scope": scope, "responsible": responsible, "municipal_only": municipal_only,
    }


def _apply_filters(cards: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    result = cards
    if filters["scope"] == SCOPE_WORK:
        result = [card for card in result if card.get("in_work")]
    if filters["municipal_only"]:
        result = [card for card in result if card.get("municipal")]
    if filters["min_floors"] >= 1:
        result = [card for card in result if int(card.get("ge1_floors") or 0) >= filters["min_floors"]]
    if filters["priority"] != "Все":
        result = [card for card in result if card.get("priority") == filters["priority"]]
    if filters["responsible"] != "Все":
        result = [card for card in result if card.get("responsible") == filters["responsible"]]
    if filters["only_overdue"]:
        result = [card for card in result if card.get("overdue")]
    if filters["query"]:
        result = [
            card for card in result
            if filters["query"] in " ".join(
                str(card.get(field) or "").lower()
                for field in ("uk_name", "uk_name_short", "uk_inn", "uk_ogrn", "uk_address")
            )
        ]
    return result


def _call_calendar_rows(cards: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = [
        {
            "Дата": str(card.get("next_action_date") or ""),
            "Время": str(card.get("next_action_time") or ""),
            "УК": str(card.get("uk_name_short") or card.get("uk_name") or ""),
            "Ответственный": str(card.get("responsible") or "—"),
            "Телефон": str(card.get("phone") or ""),
            "Цель звонка": str(card.get("next_action") or ""),
            "Часы приёма": str(card.get("reception_hours") or ""),
            "Этап": str(card.get("stage") or ""),
        }
        for card in cards
        if card.get("next_action_date") or card.get("next_action_time")
    ]
    return sorted(rows, key=lambda row: (row["Дата"] or "9999-12-31", row["Время"] or "99:99", row["УК"]))


def _render_call_calendar(cards: list[dict[str, Any]]) -> None:
    rows = _call_calendar_rows(cards)
    with st.expander(f"📅 Календарь звонков ({len(rows)})"):
        if not rows:
            st.caption("Звонки не запланированы: заполните дату и время касания в карточке УК.")
            return
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("Одинаковое время у разных УК показывается отдельными строками.")


def render_kanban_tab(service: ObjectsService) -> None:
    """Render the UK funnel board — the main waterproofing CRM screen."""
    st.caption(
        "С какими УК мы работаем, где они в воронке и что делать следующим шагом. "
        "Объекты вложены в карточку УК. Карта объектов — вторичный экран."
    )
    parking_db = get_parking_db()
    db_ok = bool(parking_db.connect())
    if not db_ok:
        st.warning(f"База объектов недоступна ({parking_db.last_error}); показаны только контуры в работе.")
    states = load_contour_states()
    uk_rows = fetch_uk_summary(parking_db, min_floors=1) if db_ok else []
    snapshot_615 = _load_615(service)
    tenders_by_key = dict(snapshot_615.get("uk") or {})
    rows_by_key = {contour_key(row): row for row in uk_rows}
    cards = [
        build_card(rows_by_key.get(key, {}), state, tenders_615=tenders_by_key.get(key))
        for key, state in states.items()
    ]
    cards += [
        build_card(row, tenders_615=tenders_by_key.get(contour_key(row)))
        for row in uk_rows if contour_key(row) not in states
    ]
    for card in cards:
        state = states.get(str(card.get("key") or ""), {})
        card["next_action_time"] = str(state.get("next_action_time") or "")
        card["reception_hours"] = str(state.get("reception_hours") or "")

    filters = _render_filters(cards, db_ok=db_ok, has_work=bool(states))
    visible = _apply_filters(cards, filters)
    if filters["scope"] == SCOPE_ALL:
        limit = st.selectbox("Показать УК", [50, 100, 200, 500], index=1, key="hydro_board_limit")
        visible = sorted(
            visible, key=lambda card: int(card.get("total_underground_floors") or 0), reverse=True
        )[:int(limit)]
    _render_kpis(visible, snapshot_615)
    if db_ok:
        _render_intake(uk_rows, states)
    drag_notice = st.session_state.pop(DRAG_NOTICE_KEY, None)
    if drag_notice:
        st.warning(str(drag_notice))
    if not visible:
        st.info("На выбранном срезе нет УК. Возьмите контур в работу из блока выше.")
        return
    st.caption("Перетащите карточку в колонку нужного этапа.")
    _render_call_calendar(visible)
    selected_key = st.session_state.get(SIDECAR_SELECTED_KEY)
    sidecar_open = bool(st.session_state.get(SIDECAR_OPEN_KEY) and selected_key)
    selected_card = next(
        (card for card in visible if str(card.get("key") or "") == str(selected_key or "")),
        None,
    )
    if sidecar_open and selected_card:
        render_inline_sidecar(
            selected_card,
            getattr(service, "crm_db", None),
            [],
            move_stage=lambda target: _move_overlay_stage(selected_card, target),
        )
    elif sidecar_open:
        st.session_state[SIDECAR_SELECTED_KEY] = None
        st.session_state[SIDECAR_OPEN_KEY] = False
        sidecar_open = False
    _render_board(
        visible,
        cards,
        selected_account_key=str(selected_key) if sidecar_open else None,
        sidecar_open=sidecar_open,
    )
