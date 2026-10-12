"""UK-centric CRM model for the waterproofing direction.

The unit of work here is a management company (УК) contour, not a single
object: one contour can bring several objects, so the funnel tracks the УК and
objects stay nested inside the contour card.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from src.services.waterproofing_funnel import (
    ACCOUNT_STAGES,
    CLOSED_STAGE,
    FUNNEL_ACCOUNT,
    STAGE_DEFAULT_ACTIONS,
    STAGE_DESCRIPTIONS,
    STAGE_LABELS,
    STAGE_TOUCH_DAYS,
    coerce_stage,
    is_closed_stage as _is_closed,
    normalize_stage,
    stage_index as _funnel_stage_index,
)
# Stage vocabulary is shared by both funnels and owned by waterproofing_funnel:
# CRM_STAGES is the УК (account) funnel shown on the main board.
CRM_STAGES: list[str] = [stage.id for stage in ACCOUNT_STAGES]
CRM_STAGE_LABELS: dict[str, str] = STAGE_LABELS
CRM_STAGE_DESCRIPTIONS: dict[str, str] = STAGE_DESCRIPTIONS
CRM_CLOSED_STAGE: str = CLOSED_STAGE.id
CLOSED_STAGES: tuple[str, ...] = (CLOSED_STAGE.id,)

PRIORITIES: tuple[str, ...] = ("Gold", "Silver", "Bronze")
PRIORITY_ICONS: dict[str, str] = {"Gold": "🥇", "Silver": "🥈", "Bronze": "🥉"}
_PRIORITY_RANK: dict[str, int] = {"Gold": 0, "Silver": 1, "Bronze": 2}


def stage_index(value: Any) -> int:
    """Zero-based position on the УК board; a closed contour sits past it."""
    return _funnel_stage_index(value, FUNNEL_ACCOUNT)


def is_closed_stage(value: Any) -> bool:
    """Whether the contour was put aside."""
    return _is_closed(value)

_UK_NAME_PREFIXES: tuple[tuple[str, str], ...] = (
    ("управляющая компания", "УК"),
    ("товарищество собственников жилья", "ТСЖ"),
    ("товарищество собственников недвижимости", "ТСЖ"),
    ("товарищество собственников", "ТСЖ"),
    ("жилищно-строительный кооператив", "ЖСК"),
    ("жилищный кооператив", "ЖК"),
    ("муниципальное унитарное предприятие", "МУП"),
)

_NAME_STOP_WORDS: frozenset[str] = frozenset(
    {"района", "район", "города", "г", "им", "имени", "и", "на", "в", "по", "от", "с"}
)


def _capitalize_uk_name(value: str) -> str:
    """Капитализировать слова названия, не ломая аббревиатуры и слово «района»."""
    words: list[str] = []
    for index, word in enumerate(value.split()):
        token = word.strip("«»\"'")
        if not token:
            continue
        if any(char.isupper() for char in token[1:]):
            words.append(token)
        elif index and token.lower() in _NAME_STOP_WORDS:
            words.append(token.lower())
        else:
            words.append("-".join(part[:1].upper() + part[1:] for part in token.split("-")))
    return " ".join(words)


def uk_display_name(value: Any) -> str:
    """Короткое имя УК: «Управляющая компания «Вк комфорт»» -> «УК «Вк Комфорт»»."""
    text = " ".join(str(value or "").split())
    if not text:
        return "Без названия"
    lowered = text.lower()
    if lowered.startswith("гбу"):
        inner = _capitalize_uk_name(text[3:])
        return f"ГБУ «{inner}»" if inner else "ГБУ"
    for prefix, short in _UK_NAME_PREFIXES:
        if lowered.startswith(prefix):
            inner = _capitalize_uk_name(text[len(prefix):])
            return f"{short} «{inner}»" if inner else short
    return _capitalize_uk_name(text)


def is_municipal_uk(value: Any) -> bool:
    """ГБУ «Жилищник» — муниципальные УК, которые показываем первыми."""
    lowered = str(value or "").lower()
    return "жилищник" in lowered or lowered.startswith("гбу")


def default_priority(parkings: int, total_underground_floors: int) -> str:
    """Gold/Silver/Bronze по масштабу подземной гидроизоляции.

    Считаем не число объектов, а объём работ: количество паркингов и сумму
    подземных этажей. 11 паркингов по 2 этажа (22 уровня) и 3 паркинга по
    5 этажей (15 уровней) — оба случая крупные, поэтому оба Gold.
    Менеджер может переопределить приоритет вручную в карточке УК.
    """
    parking_count = max(0, int(parkings or 0))
    floors = max(0, int(total_underground_floors or 0))
    if floors >= 10 or parking_count >= 5:
        return "Gold"
    if floors >= 4 or parking_count >= 3:
        return "Silver"
    return "Bronze"


def priority_reason(parkings: int, total_underground_floors: int) -> str:
    """Пояснение приоритета для карточки: паркинги и подземные этажи."""
    parking_count = max(0, int(parkings or 0))
    floors = max(0, int(total_underground_floors or 0))
    return f"{parking_count} паркинг(ов) · {floors} подземных этажей"


def normalize_priority(value: Any, parkings: int, total_underground_floors: int) -> str:
    text = str(value or "").strip().capitalize()
    if text in PRIORITIES:
        return text
    return default_priority(parkings, total_underground_floors)


def priority_icon(priority: str) -> str:
    return PRIORITY_ICONS.get(priority, PRIORITY_ICONS["Bronze"])


def priority_rank(priority: str) -> int:
    return _PRIORITY_RANK.get(priority, len(PRIORITIES))


def parse_amount(value: Any) -> float:
    """Parse rubles from a number or free text such as "4,2 млн"."""
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value or "").strip().lower().replace("\u00a0", "").replace(" ", "")
    if not text:
        return 0.0
    multiplier = 1.0
    for suffix, factor in (("млн", 1_000_000.0), ("тыс", 1_000.0)):
        if suffix in text:
            multiplier = factor
            text = text.replace(suffix, "")
            break
    text = text.replace("₽", "").replace("руб", "").replace("р.", "").replace(",", ".")
    try:
        return max(0.0, float(text) * multiplier)
    except ValueError:
        return 0.0


def format_amount(value: Any) -> str:
    """Format rubles for a board card."""
    amount = parse_amount(value)
    if amount <= 0:
        return "—"
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f} млн ₽".replace(".0 млн", " млн")
    if amount >= 1_000:
        return f"{amount / 1_000:.1f} тыс ₽".replace(".0 тыс", " тыс")
    return f"{amount:.0f} ₽"


def parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def next_touch_default(stage: Any, *, today: date | None = None) -> str:
    """Default next-touch date for a stage, from its follow-up cadence."""
    days = STAGE_TOUCH_DAYS.get(normalize_stage(stage), 3)
    return ((today or date.today()) + timedelta(days=days)).isoformat()


def has_tech_contact(state: dict[str, Any] | None) -> bool:
    """A tech contact exists once a person or a direct phone was saved."""
    if not state:
        return False
    return bool(
        str(state.get("exploitation_contact") or "").strip()
        or str(state.get("tech_contact_phone") or "").strip()
    )


def overdue_days(state: dict[str, Any] | None, *, today: date | None = None) -> int:
    """Whole days past the planned next touch; 0 when nothing is overdue."""
    if not state or is_closed_stage(state.get("stage")):
        return 0
    planned = parse_date(state.get("next_action_date"))
    if not planned:
        return 0
    return max(0, ((today or date.today()) - planned).days)


def is_overdue(state: dict[str, Any] | None, *, today: date | None = None) -> bool:
    return overdue_days(state, today=today) > 0


def contour_key(row: dict[str, Any]) -> str:
    """Stable identity of a management-company contour across CRM and UI."""
    return str(
        row.get("uk_ogrn") or row.get("uk_inn") or row.get("uk_id") or row.get("uk_name") or ""
    ).strip()


def build_card(
    uk_row: dict[str, Any],
    state: dict[str, Any] | None = None,
    *,
    tenders_615: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge a database УК row with its saved CRM state into one board card."""
    state = state or {}
    raw_name = str(uk_row.get("uk_name") or state.get("uk_name") or "")
    object_count = int(uk_row.get("object_count") or state.get("object_count") or 0)
    parking_count = int(uk_row.get("parking_count") or state.get("parking_count") or 0)
    total_floors = int(
        uk_row.get("total_underground_floors") or state.get("total_underground_floors") or 0
    )
    max_floors = int(
        uk_row.get("max_underground_floors") or state.get("max_underground_floors") or 0
    )
    ge1_floors = int(uk_row.get("ge1_floors") or state.get("ge1_floors") or 0)
    ge2_floors = int(uk_row.get("ge2_floors") or state.get("ge2_floors") or 0)
    # Coerced, not merely normalised: a contour saved at an object-funnel stage
    # must land in the account column that reflects it, not restart from zero.
    stage = coerce_stage(state.get("stage"), FUNNEL_ACCOUNT)
    priority = normalize_priority(state.get("priority"), parking_count, total_floors)
    amount = parse_amount(state.get("potential_amount"))
    tenders = tenders_615 or {}
    return {
        "key": str(state.get("key") or "") or contour_key(uk_row),
        "uk_name": raw_name or "Без названия",
        "uk_name_short": uk_display_name(raw_name),
        "uk_inn": uk_row.get("uk_inn") or state.get("uk_inn") or "—",
        "uk_ogrn": uk_row.get("uk_ogrn") or state.get("uk_ogrn") or "—",
        "uk_address": str(uk_row.get("uk_address") or state.get("uk_address") or ""),
        "uk_phone": uk_row.get("uk_phone") or state.get("uk_phone") or "",
        "phone": state.get("secretary_phone") or uk_row.get("uk_phone") or state.get("uk_phone") or "",
        "municipal": is_municipal_uk(raw_name),
        "object_count": object_count,
        "parking_count": parking_count,
        "total_underground_floors": total_floors,
        "max_underground_floors": max_floors,
        "ge1_floors": ge1_floors,
        "ge2_floors": ge2_floors,
        "potential_amount": amount,
        "potential_amount_label": format_amount(amount),
        "priority": priority,
        "priority_icon": priority_icon(priority),
        "priority_reason": priority_reason(parking_count, total_floors),
        "tenders_615_count": int(tenders.get("history_tenders") or tenders.get("tenders") or 0),
        "tenders_615_amount": float(tenders.get("history_amount") or tenders.get("amount") or 0.0),
        "tenders_615_amount_label": format_amount(
            tenders.get("history_amount") or tenders.get("amount") or 0
        ),
        "tenders_615_waterproofing": int(
            tenders.get("history_waterproofing_tenders") or tenders.get("waterproofing_tenders") or 0
        ),
        "tenders_615_last_date": str(
            tenders.get("history_last_date") or tenders.get("last_date") or ""
        ),
        "tenders_615_year": str(tenders.get("year") or ""),
        "tenders_615_year_count": int(tenders.get("tenders") or 0),
        "tenders_615_year_amount": float(tenders.get("amount") or 0.0),
        "tenders_615_year_amount_label": format_amount(tenders.get("amount") or 0),
        "tenders_615_years": [int(year) for year in (tenders.get("years") or [])],
        "tenders_615_approximate": int(tenders.get("approximate_matches") or 0),
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "stage_description": STAGE_DESCRIPTIONS.get(stage, ""),
        "stage_index": stage_index(stage),
        "next_action": state.get("next_action") or STAGE_DEFAULT_ACTIONS.get(stage, "—"),
        "next_action_date": str(state.get("next_action_date") or ""),
        "tech_contact": has_tech_contact(state),
        "tech_contact_person": str(state.get("exploitation_contact") or ""),
        "responsible": str(state.get("responsible") or "").strip() or "—",
        "overdue": is_overdue(state),
        "overdue_days": overdue_days(state),
        "in_work": bool(state),
        "note": str(state.get("note") or ""),
        "updated_at": str(state.get("updated_at") or ""),
    }


def sort_cards(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Порядок карточек: просрочка, затем приоритет, ГБУ «Жилищник», дата касания."""
    return sorted(
        cards,
        key=lambda card: (
            0 if card.get("overdue") else 1,
            priority_rank(str(card.get("priority"))),
            0 if card.get("municipal") else 1,
            card.get("next_action_date") or "9999-12-31",
            str(card.get("uk_name_short") or card.get("uk_name") or ""),
        ),
    )


def kanban_columns(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group cards into funnel columns, keeping the fixed stage order."""
    grouped: dict[str, list[dict[str, Any]]] = {stage: [] for stage in CRM_STAGES}
    for card in sort_cards(cards):
        stage = coerce_stage(card.get("stage"), FUNNEL_ACCOUNT)
        if stage in grouped:
            grouped[stage].append(card)
    return [
        {
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, stage),
            "stage_description": STAGE_DESCRIPTIONS.get(stage, ""),
            "stage_index": stage_index(stage),
            "index": index,
            "cards": grouped[stage],
            "count": len(grouped[stage]),
            "amount_label": format_amount(sum(float(c.get("potential_amount") or 0) for c in grouped[stage])),
        }
        for index, stage in enumerate(CRM_STAGES)
    ]


def board_kpis(cards: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the numbers the main screen reports at the top."""
    rows = list(cards)
    amount = sum(float(card.get("potential_amount") or 0) for card in rows)
    tenders_amount = sum(float(card.get("tenders_615_amount") or 0) for card in rows)
    tenders_year_amount = sum(
        float(card.get("tenders_615_year_amount") or 0)
        for card in rows
    )
    return {
        "contours": len(rows),
        "in_work": sum(1 for card in rows if card.get("in_work")),
        "objects": sum(int(card.get("object_count") or 0) for card in rows),
        "parkings": sum(int(card.get("parking_count") or 0) for card in rows),
        "underground_objects": sum(int(card.get("ge1_floors") or 0) for card in rows),
        "underground_floors": sum(int(card.get("total_underground_floors") or 0) for card in rows),
        "ge2_floors": sum(int(card.get("ge2_floors") or 0) for card in rows),
        "municipal": sum(1 for card in rows if card.get("municipal")),
        "overdue": sum(1 for card in rows if card.get("overdue")),
        "with_tech_contact": sum(1 for card in rows if card.get("tech_contact")),
        "tenders_615": sum(int(card.get("tenders_615_count") or 0) for card in rows),
        "tenders_615_amount": tenders_amount,
        "tenders_615_amount_label": format_amount(tenders_amount),
        "tenders_615_uk": sum(1 for card in rows if card.get("tenders_615_count")),
        "tenders_615_year": sum(int(card.get("tenders_615_year_count") or 0) for card in rows),
        "tenders_615_year_amount": tenders_year_amount,
        "tenders_615_year_amount_label": format_amount(tenders_year_amount),
        "amount": amount,
        "amount_label": format_amount(amount),
    }


__all__ = [
    "CLOSED_STAGES",
    "CRM_CLOSED_STAGE",
    "CRM_STAGE_LABELS",
    "CRM_STAGES",
    "PRIORITIES",
    "PRIORITY_ICONS",
    "STAGE_DEFAULT_ACTIONS",
    "STAGE_TOUCH_DAYS",
    "board_kpis",
    "build_card",
    "default_priority",
    "format_amount",
    "has_tech_contact",
    "is_closed_stage",
    "is_municipal_uk",
    "is_overdue",
    "kanban_columns",
    "next_touch_default",
    "normalize_priority",
    "normalize_stage",
    "overdue_days",
    "parse_amount",
    "parse_date",
    "priority_icon",
    "priority_rank",
    "priority_reason",
    "uk_display_name",
    "sort_cards",
    "stage_index",
]
