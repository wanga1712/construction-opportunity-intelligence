"""Deterministic guards and fallbacks for object AI classification."""
from __future__ import annotations

from typing import Optional

from src.services.object_category_labels import SEGMENT_LABELS
from src.services.object_lifecycle import (
    DEFAULT_SALES_WINDOW_DAYS,
    delivery_days_left,
    is_awarded,
    tender_days_left,
)
from src.services.object_models import ObjectViewItem


def label_for_segment(segment: str, fallback: Optional[str] = None) -> str:
    from src.services.object_category_labels import segment_from_label

    if fallback and segment_from_label(fallback) == segment:
        return fallback
    return SEGMENT_LABELS.get(segment, SEGMENT_LABELS["other"])


def guarded_segment(item: ObjectViewItem, segment: str, label: str) -> tuple[str, str]:
    """Deterministic guardrails over model output for obvious CRM cases."""
    text = " ".join(
        str(x or "")
        for x in (
            item.name,
            item.address,
            item.balance_holder,
            item.customer_name,
            item.status,
            item.registry_type,
        )
    ).lower()

    # Явные учреждения — сильнее дорожных слов в том же названии
    # (школа + благоустройство двора ≠ road_infrastructure).
    social_strong = (
        "мбоу", "сош", "школ", "детсад", "детский сад", "гбуз", "больниц",
        "поликлиник", "амбулатор", "родильн", "колледж", "университет",
        "культурного наследия", "социального обслуж",
    )
    social_weak = ("учрежден", "муниципаль", "казенн", "бюджетн")
    residential_tokens = ("мкд", "многоквартир", "жилой дом", "жилого дома", "жилых домов", "жк ")
    # Только явная дорожная инфраструктура как объект закупки, не двор/ограждение школы.
    road_tokens = (
        "автомобильн дорог", "ремонт дорог", "содержание дорог", "ул.",
        "путепровод", "эстакад", "тоннел", "развязк", "проезж части",
        "тротуарн", "мостов", "моста ", "мост ",
    )
    industrial_tokens = (
        "завод", "производств", "промышлен", "цех", "склад", "котельн",
        "насосн", "очистн", "водозабор", "подстанц",
    )

    if any(t in text for t in social_strong):
        return "social", SEGMENT_LABELS["social"]
    if any(t in text for t in residential_tokens):
        return "residential", SEGMENT_LABELS["residential"]
    if any(t in text for t in road_tokens):
        return "road_infrastructure", SEGMENT_LABELS["road_infrastructure"]
    if any(t in text for t in social_weak):
        return "social", SEGMENT_LABELS["social"]
    if any(t in text for t in industrial_tokens):
        return "industrial", SEGMENT_LABELS["industrial"]
    if "223" in str(item.registry_type):
        return "commercial", SEGMENT_LABELS["commercial"]
    return segment, label


def sanitize_volume_signal(item: ObjectViewItem, volume_signal: str) -> str:
    """Never claim material volume without confirmed document matches."""
    value = (volume_signal or "").strip() or "неизвестно"
    if int(item.doc_matches or 0) <= 0:
        return "неизвестно"
    return value


def fallback_sales_action(item: ObjectViewItem, current: str = "") -> str:
    if current in {"direct_bid", "wait_contractor", "monitor_only", "reject"}:
        return current
    delivery_days = delivery_days_left(item)
    tender_days = tender_days_left(item)
    if delivery_days is not None and delivery_days < DEFAULT_SALES_WINDOW_DAYS:
        return "monitor_only"
    if is_awarded(item) or (tender_days is not None and tender_days < 0):
        return "wait_contractor"
    if tender_days is not None and tender_days >= 2:
        return "direct_bid"
    return "monitor_only"


def fallback_priority(item: ObjectViewItem, score: int = 0) -> int:
    if score > 0:
        value = max(0, min(100, score))
    else:
        value = 25
        if item.doc_matches:
            value += min(25, int(item.doc_matches))
        if item.matched_files:
            value += min(15, int(item.matched_files) * 2)
        text = (item.name or "").lower()
        if any(t in text for t in ("капитальн", "ремонт", "строительств", "реконструкц", "реставрац")):
            value += 15

    delivery_days = delivery_days_left(item)
    sales_action = fallback_sales_action(item)
    if delivery_days is not None and delivery_days < DEFAULT_SALES_WINDOW_DAYS:
        return 0
    if sales_action == "direct_bid":
        value += 12
    elif sales_action == "wait_contractor":
        value += 6
    elif sales_action == "monitor_only":
        value -= 20
    return max(0, min(100, value))


def fallback_delivery_chance(item: ObjectViewItem, current: str = "") -> str:
    value = current.strip().lower()
    if value in {"высокий", "средний", "низкий"}:
        return value
    days = delivery_days_left(item)
    if days is None:
        return "средний"
    if days < DEFAULT_SALES_WINDOW_DAYS:
        return "низкий"
    if days <= 150:
        return "средний"
    return "высокий"
