"""Board-level aggregation for the two waterproofing funnels.

Pure numbers for the KPI strip: no Streamlit, no database access. Every value is
derived from cards that already exist, so the strip can never show a demo figure.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Mapping

from src.services.waterproofing_crm import (
    format_amount,
    is_closed_stage,
    parse_amount,
    sort_cards,
)
from src.services.waterproofing_deals import deal_kpis
from src.services.waterproofing_funnel import (
    FUNNEL_ACCOUNT,
    board_columns,
    coerce_stage,
    normalize_stage,
)


def account_kpis(cards: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """УК-board numbers: contours in work, their portfolio and overdue touches."""
    rows = [card for card in cards if not is_closed_stage(card.get("stage"))]
    amount = sum(parse_amount(card.get("potential_amount")) for card in rows)
    return {
        "accounts": len(rows),
        "objects": sum(int(card.get("object_count") or 0) for card in rows),
        "parkings": sum(int(card.get("parking_count") or 0) for card in rows),
        "underground_floors": sum(int(card.get("total_underground_floors") or 0) for card in rows),
        "municipal": sum(1 for card in rows if card.get("municipal")),
        "with_tech_contact": sum(1 for card in rows if card.get("tech_contact")),
        "overdue": sum(1 for card in rows if card.get("overdue")),
        "amount": amount,
        "amount_label": format_amount(amount),
    }


def pipeline_amount(
    account_cards: Iterable[dict[str, Any]], deal_cards: Iterable[dict[str, Any]]
) -> float:
    """Pipeline value without double counting an УК that already has object deals.

    Money belongs to objects. An УК-level estimate is only added while none of its
    objects has its own deal estimate yet.
    """
    deals = list(deal_cards)
    deal_keys = {str(card.get("uk_key") or "") for card in deals}
    deal_amount = sum(parse_amount(card.get("potential_amount")) for card in deals)
    account_only = [
        card
        for card in account_cards
        if not is_closed_stage(card.get("stage")) and str(card.get("key") or "") not in deal_keys
    ]
    return deal_amount + sum(parse_amount(card.get("potential_amount")) for card in account_only)


def dashboard_kpis(
    account_cards: Iterable[dict[str, Any]], deal_cards: Iterable[dict[str, Any]]
) -> list[dict[str, str]]:
    """Compact KPI strip for the whole section, shared by both boards."""
    accounts = list(account_cards)
    deals = list(deal_cards)
    account = account_kpis(accounts)
    deal = deal_kpis(deals)
    return [
        {"icon": "🏢", "label": "УК в работе", "value": str(account["accounts"])},
        {"icon": "🏗", "label": "Объектов", "value": str(account["objects"])},
        {"icon": "🔍", "label": "Обследований", "value": str(deal["survey"])},
        {"icon": "📄", "label": "КП выдано", "value": str(deal["proposal"])},
        {"icon": "⚖️", "label": "В закупке", "value": str(deal["procurement"])},
        {
            "icon": "💰",
            "label": "Сумма pipeline",
            "value": format_amount(pipeline_amount(accounts, deals)),
        },
    ]


_DISTRICT_AFTER = re.compile(
    r"района\s+([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]*(?:\s+[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]*)?)",
    re.IGNORECASE,
)
_DISTRICT_BEFORE = re.compile(
    r"([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]*)\s+района", re.IGNORECASE
)


def uk_district(card: dict[str, Any]) -> str:
    """District extracted from the УК name, or "" when it is not stated.

    The database has no district column, so the only honest source is the name
    itself («ГБУ «Жилищник района Хамовники»» -> «Хамовники»). УК without a
    district in the name stay ungrouped instead of being guessed.
    """
    name = str(card.get("uk_name") or "")
    for pattern in (_DISTRICT_AFTER, _DISTRICT_BEFORE):
        match = pattern.search(name)
        if match:
            words = " ".join(match.group(1).split()).strip("«»\"' ")
            if words:
                return words.title()
    return ""


def uk_districts(cards: Iterable[dict[str, Any]]) -> list[str]:
    """Districts actually present among the given cards, alphabetically."""
    return sorted({value for value in (uk_district(card) for card in cards) if value})


def _is_any(value: Any) -> bool:
    """Whether a toolbar value means «no restriction» instead of a real choice."""
    text = str(value if value is not None else "").strip()
    return not text or text.lower().startswith("все") or text in ("Любой", "Любая")


def account_columns(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group УК cards into the four account columns of the first funnel."""
    columns = board_columns(FUNNEL_ACCOUNT)
    by_stage = {column["stage"]: column for column in columns}
    for card in sort_cards(cards):
        column = by_stage.get(coerce_stage(card.get("stage"), FUNNEL_ACCOUNT))
        if column is not None:
            column["cards"].append(card)
    for column in columns:
        column["count"] = len(column["cards"])
        column["amount_label"] = format_amount(
            sum(parse_amount(card.get("potential_amount")) for card in column["cards"])
        )
    return columns


def apply_filters(
    cards: Iterable[dict[str, Any]],
    filters: Mapping[str, Any],
    *,
    district_of: Callable[[dict[str, Any]], str] | None = None,
    active_of: Callable[[dict[str, Any]], bool] | None = None,
    search_fields: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Narrow a board down to the toolbar selection, inventing nothing.

    "District" only exists inside the УК name and "active object" means
    different things on the two boards, so both predicates are injected by the
    caller instead of being guessed here. Stage matching uses the canonical
    stage id, so a legacy saved value still lands in the right column.
    """
    query = str(filters.get("query") or "").strip().lower()
    stage = "" if _is_any(filters.get("stage")) else str(filters.get("stage")).strip()
    district = "" if _is_any(filters.get("district")) else str(filters.get("district")).strip()
    responsible = (
        "" if _is_any(filters.get("responsible")) else str(filters.get("responsible")).strip()
    )
    fields = tuple(search_fields)
    result: list[dict[str, Any]] = []
    for card in cards:
        if stage and normalize_stage(card.get("stage")) != stage:
            continue
        if district and district_of is not None and district_of(card) != district:
            continue
        if responsible and str(card.get("responsible") or "").strip() != responsible:
            continue
        if filters.get("overdue") and not card.get("overdue"):
            continue
        if filters.get("active_only") and active_of is not None and not active_of(card):
            continue
        if query and fields:
            haystack = " ".join(str(card.get(field) or "") for field in fields).lower()
            if query not in haystack:
                continue
        result.append(card)
    return result


__all__ = [
    "account_columns",
    "account_kpis",
    "apply_filters",
    "dashboard_kpis",
    "pipeline_amount",
    "uk_district",
    "uk_districts",
]
