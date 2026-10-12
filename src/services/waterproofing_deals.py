"""Object-level deal funnel for the waterproofing CRM.

Once a concrete object appears, the unit of work stops being the УК and becomes
that object: one УК can have an object on торги while another object of the same
УК is only surveyed. Deal state is therefore stored per object, apart from the
УК contour state.

Storage is an append-only JSONL journal where the newest record wins - the same
contract the contour journal already uses, so history stays readable.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from src.services.waterproofing_crm import (
    contour_key,
    format_amount,
    is_overdue,
    normalize_priority,
    overdue_days,
    parse_amount,
    priority_icon,
    priority_rank,
    uk_display_name,
)
from src.services.waterproofing_funnel import (
    DEAL_STAGES,
    FUNNEL_DEAL,
    STAGE_DEFAULT_ACTIONS,
    STAGE_DESCRIPTIONS,
    STAGE_LABELS,
    board_columns,
    coerce_stage,
    stage_index,
)

_DEAL_PATH = Path(__file__).resolve().parents[2] / "data" / "waterproofing" / "deal_states.jsonl"
_RANK: dict[str, int] = {stage.id: index for index, stage in enumerate(DEAL_STAGES)}


def deal_key(row: dict[str, Any]) -> str:
    """Stable identity of an object deal across storage and UI."""
    return str(
        row.get("cadastral_number")
        or row.get("object_id")
        or row.get("id")
        or row.get("address")
        or row.get("name")
        or ""
    ).strip()


def _journal_rows() -> list[dict[str, Any]]:
    if not _DEAL_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in _DEAL_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def load_deal_states() -> dict[str, dict[str, Any]]:
    """Newest saved state for every object deal."""
    states: dict[str, dict[str, Any]] = {}
    for row in _journal_rows():
        key = str(row.get("key") or "")
        if key:
            states[key] = row
    return states


def latest_deal_state(key: str) -> dict[str, Any]:
    """Newest saved record of one deal, or an empty dict."""
    latest: dict[str, Any] = {}
    for row in _journal_rows():
        if str(row.get("key") or "") == key:
            latest = row
    return latest


def save_deal_state(key: str, data: dict[str, Any]) -> dict[str, Any]:
    """Append a new immutable deal state record."""
    _DEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"key": key, "updated_at": date.today().isoformat(), **data}
    with _DEAL_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def merge_deal_state(key: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Append a record that inherits every field of the newest saved state."""
    merged = {
        field: value
        for field, value in latest_deal_state(key).items()
        if field not in ("key", "updated_at")
    }
    merged.update(patch)
    return save_deal_state(key, merged)


def deal_sort_key(card: dict[str, Any]) -> tuple[Any, ...]:
    """Overdue first, then priority, then the planned next touch."""
    return (
        0 if card.get("overdue") else 1,
        priority_rank(str(card.get("priority"))),
        card.get("next_action_date") or "9999-12-31",
        str(card.get("name") or ""),
    )


def build_deal_card(
    object_row: dict[str, Any],
    uk_row: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge one object with its УК and saved deal state into a board card."""
    state = state or {}
    uk_row = uk_row or {}
    stage = coerce_stage(state.get("stage"), FUNNEL_DEAL)
    amount = parse_amount(state.get("potential_amount"))
    uk_name = str(uk_row.get("uk_name") or state.get("uk_name") or "")
    floors = object_row.get("floors_underground") or state.get("floors_underground") or 0
    priority = normalize_priority(state.get("priority"), 1, int(floors or 0))
    return {
        "key": str(state.get("key") or "") or deal_key(object_row),
        "name": str(object_row.get("name") or object_row.get("address") or "Объект"),
        "address": str(object_row.get("address") or state.get("address") or ""),
        "cadastral_number": str(
            object_row.get("cadastral_number") or state.get("cadastral_number") or ""
        ),
        "floors_underground": floors,
        "area_total": object_row.get("area_total") or state.get("area_total") or "",
        "uk_key": contour_key(uk_row) if uk_row else str(state.get("uk_key") or ""),
        "uk_name": uk_name or "—",
        "uk_name_short": uk_display_name(uk_name) if uk_name else "—",
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "stage_description": STAGE_DESCRIPTIONS.get(stage, ""),
        "stage_index": stage_index(stage, FUNNEL_DEAL),
        "next_action": str(state.get("next_action") or STAGE_DEFAULT_ACTIONS.get(stage, "—")),
        "next_action_date": str(state.get("next_action_date") or ""),
        "survey_date": str(state.get("survey_date") or ""),
        "potential_amount": amount,
        "potential_amount_label": format_amount(amount),
        "priority": priority,
        "priority_icon": priority_icon(priority),
        "responsible": str(state.get("responsible") or "").strip() or "—",
        "overdue": is_overdue(state),
        "overdue_days": overdue_days(state),
        "in_work": bool(state),
        "note": str(state.get("note") or ""),
        "updated_at": str(state.get("updated_at") or ""),
    }


def deal_columns(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group object cards into the five deal columns."""
    columns = board_columns(FUNNEL_DEAL)
    by_stage = {column["stage"]: column for column in columns}
    for card in sorted(cards, key=deal_sort_key):
        column = by_stage.get(coerce_stage(card.get("stage"), FUNNEL_DEAL))
        if column is not None:
            column["cards"].append(card)
    for column in columns:
        column["count"] = len(column["cards"])
        column["amount_label"] = format_amount(
            sum(float(card.get("potential_amount") or 0) for card in column["cards"])
        )
    return columns


def deal_kpis(cards: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Numbers the object board reports: reached survey / КП / закупка / контракт."""
    rows = list(cards)
    amount = sum(float(card.get("potential_amount") or 0) for card in rows)

    def reached(stage_id: str) -> int:
        rank = _RANK[stage_id]
        return sum(1 for card in rows if int(card.get("stage_index") or 0) >= rank)

    return {
        "deals": len(rows),
        "survey": reached("survey"),
        "proposal": reached("proposal"),
        "procurement": reached("procurement"),
        "contract": reached("contract"),
        "overdue": sum(1 for card in rows if card.get("overdue")),
        "amount": amount,
        "amount_label": format_amount(amount),
    }
