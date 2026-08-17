"""Stage-specific scoring для razygranye (AWARDED) объектов.
НЕ использовать для OPEN/torgi — логика принципиально другая.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from enum import Enum
from typing import Optional
import statistics


class AwardedLevel(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"
    WOOD = "WOOD"
    OUT_OF_PROFILE = "OUT_OF_PROFILE"
    NON_ACTIONABLE = "NON_ACTIONABLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# Sort order для отображения (ниже = выше в списке)
_LEVEL_ORDER: dict[AwardedLevel, int] = {
    AwardedLevel.GOLD: 0,
    AwardedLevel.SILVER: 1,
    AwardedLevel.BRONZE: 2,
    AwardedLevel.NEEDS_REVIEW: 3,
    AwardedLevel.WOOD: 4,
    AwardedLevel.OUT_OF_PROFILE: 5,
    AwardedLevel.NON_ACTIONABLE: 6,
}


# ─── Cohort key helpers ────────────────────────────────────────────────────────

def _cohort_key(card: dict) -> tuple:
    """Cohort = (category, subcategory/okpd_prefix, procurement_type/source_table)."""
    cat = card.get("crm_category") or ""
    okpd = card.get("okpd_code") or ""
    # Берём первые 2 сегмента ОКПД как «подкатегория»
    subcat = ".".join(okpd.split(".")[:2]) if okpd else ""
    ptype = card.get("source_table") or ""
    return (cat, subcat, ptype)


def compute_cohort_medians(cards: list[dict]) -> dict[tuple, float]:
    """
    Вычислить медианы initial_price по cohort (category, subcategory, procurement_type).
    Cohort < 3 объектов — не включать (медиана не считается надёжной).
    Возвращает {(cat, subcat, ptype): median_price}.
    """
    groups: dict[tuple, list[float]] = defaultdict(list)
    for card in cards:
        price = card.get("initial_price") or card.get("final_contract_price")
        if price is None:
            continue
        key = _cohort_key(card)
        groups[key].append(float(price))

    return {
        key: statistics.median(prices)
        for key, prices in groups.items()
        if len(prices) >= 3
    }


# ─── Delivery date resolution ─────────────────────────────────────────────────

def _delivery_end(card: dict) -> Optional[date]:
    """Приоритет: execution_end_at -> delivery_end_date."""
    for field in ("execution_end_at", "delivery_end_date"):
        val = card.get(field)
        if val is not None:
            if isinstance(val, date):
                return val
    return None


def days_to_delivery_end(card: dict, today: date) -> Optional[int]:
    end = _delivery_end(card)
    if end is None:
        return None
    return (end - today).days


# ─── Object type helpers ───────────────────────────────────────────────────────

def _is_construction(obj_type: str, okpd: str) -> bool:
    obj_lower = (obj_type or "").lower()
    okpd_lower = (okpd or "").lower()
    construction_keywords = ("строи", "ремонт", "реконструк", "монтаж")
    return (
        any(k in obj_lower for k in construction_keywords)
        or okpd_lower.startswith("41")
        or okpd_lower.startswith("42")
        or okpd_lower.startswith("43")
    )


def _is_computers(obj_type: str, okpd: str, crm_category: str) -> bool:
    combined = " ".join([obj_type or "", okpd or "", crm_category or ""]).lower()
    return any(k in combined for k in ("компьютер", "вычислит", "it", "26.20", "орг.техник"))


# ─── Main scoring function ─────────────────────────────────────────────────────

def score_awarded(
    card: dict,
    category_median: Optional[float] = None,
    today: Optional[date] = None,
) -> tuple[AwardedLevel, list[str]]:
    """
    Вернуть (level, reason_codes).
    reason_codes — список причин для показа в карточке.

    category_median=None когда cohort < 3 — медианное сравнение не проводится.
    """
    if today is None:
        today = date.today()

    reasons: list[str] = []
    price = float(card.get("initial_price") or card.get("final_contract_price") or 0)
    evidence = int(card.get("evidence_count") or 0)
    match_count = int(card.get("match_count") or card.get("interesting_count") or 0)
    contractor = card.get("contractor_name") or card.get("winner_name") or ""
    crm_category = card.get("crm_category") or ""
    okpd = card.get("okpd_code") or ""
    obj_type = card.get("object_type") or ""

    d_left = days_to_delivery_end(card, today)

    # ── 1. Нет даты окончания → NEEDS_REVIEW ──────────────────────────────
    if d_left is None:
        reasons.append("no_delivery_date")
        return AwardedLevel.NEEDS_REVIEW, reasons

    # ── 2. Окно поставки истекло → OUT_OF_PROFILE ─────────────────────────
    if d_left < 0:
        reasons.append("delivery_expired")
        return AwardedLevel.OUT_OF_PROFILE, reasons

    # ── 3. Окно практически закрыто (< 7 дней) → WOOD ────────────────────
    if d_left < 7:
        reasons.append(f"window_nearly_closed:{d_left}d")
        return AwardedLevel.WOOD, reasons

    # ── 4. Нет evidence и нет matches → NEEDS_REVIEW ─────────────────────
    has_evidence = evidence > 0 or match_count > 0
    # Строительные работы: требуем подтверждённую материальную часть
    is_construction = _is_construction(obj_type, okpd)
    if is_construction and evidence == 0:
        reasons.append("construction_no_material_evidence")
        has_evidence = False

    if not has_evidence:
        reasons.append("no_evidence")
        return AwardedLevel.NEEDS_REVIEW, reasons

    # ── 5. Computers/IT: проектировщик не нужен ───────────────────────────
    is_computers = _is_computers(obj_type, okpd, crm_category)
    if is_computers:
        reasons.append("computers_direct_supply_ok")

    # ── 6. Медиана: сравнение объёма ──────────────────────────────────────
    above_median: Optional[bool] = None
    if category_median is not None and price > 0:
        above_median = price >= category_median
        ratio = price / category_median
        if above_median:
            reasons.append(f"above_median:{ratio:.1f}x")
        else:
            reasons.append(f"below_median:{ratio:.1f}x")
    else:
        reasons.append("no_cohort_median")

    # ── 7. Победитель ──────────────────────────────────────────────────────
    has_contractor = bool(contractor.strip())

    # ── 8. Срок поставки ──────────────────────────────────────────────────
    gold_time = d_left >= 30
    if gold_time:
        reasons.append(f"days_left:{d_left}")
    elif d_left >= 14:
        reasons.append(f"days_left_silver:{d_left}")
    elif d_left >= 7:
        reasons.append(f"days_left_bronze:{d_left}")

    # ── 9. GOLD: все критерии ─────────────────────────────────────────────
    gold_median = above_median is not False  # True или None (нет данных — не блокируем)
    if gold_time and has_evidence and gold_median and has_contractor:
        reasons.append("all_gold_criteria_met")
        return AwardedLevel.GOLD, reasons

    # ── 10. Определяем недостающие критерии ───────────────────────────────
    missing = []
    if not gold_time:
        missing.append("time")
    if above_median is False:
        missing.append("median")
    if not has_contractor:
        missing.append("contractor")

    # BRONZE zone (7-13 дней)
    if d_left < 14:
        reasons.append("bronze_zone")
        reasons.extend([f"missing_{m}" for m in missing])
        return AwardedLevel.BRONZE, reasons

    # SILVER: частичное соответствие (до 2 недостающих критериев, есть evidence)
    if len(missing) <= 2:
        reasons.extend([f"missing_{m}" for m in missing])
        return AwardedLevel.SILVER, reasons

    # Много критериев не выполнено → NEEDS_REVIEW
    reasons.extend([f"missing_{m}" for m in missing])
    reasons.append("insufficient_criteria")
    return AwardedLevel.NEEDS_REVIEW, reasons


# ─── Sort key ─────────────────────────────────────────────────────────────────

def awarded_sort_key(card: dict) -> tuple[int, int]:
    """Sort: GOLD > SILVER > BRONZE > NEEDS_REVIEW > WOOD > OUT_OF_PROFILE."""
    level_str = card.get("awarded_level", AwardedLevel.NEEDS_REVIEW)
    try:
        level = AwardedLevel(level_str)
    except ValueError:
        level = AwardedLevel.NEEDS_REVIEW
    order = _LEVEL_ORDER.get(level, 99)
    d_left = card.get("_days_to_delivery") or 0
    return (order, -d_left)
