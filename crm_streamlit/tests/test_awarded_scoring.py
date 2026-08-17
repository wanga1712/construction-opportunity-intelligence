"""Tests for awarded stage-specific scoring.

Run:
  cd /opt/CRM_Streamlit
  PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89 .venv313/bin/pytest tests/test_awarded_scoring.py -q
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.services.awarded_scoring import (
    AwardedLevel,
    compute_cohort_medians,
    score_awarded,
    awarded_sort_key,
)

TODAY = date(2026, 8, 5)
FUTURE_60 = TODAY + timedelta(days=60)
FUTURE_20 = TODAY + timedelta(days=20)
FUTURE_10 = TODAY + timedelta(days=10)
FUTURE_3  = TODAY + timedelta(days=3)
PAST      = TODAY - timedelta(days=5)


def _card(**kwargs) -> dict:
    base = {
        "initial_price": 5_000_000,
        "evidence_count": 5,
        "match_count": 3,
        "contractor_name": "ООО Поставщик",
        "delivery_end_date": FUTURE_60,
        "crm_category": "computers",
        "okpd_code": "26.20.11",
        "object_type": "компьютеры",
        "source_table": "zakupki_gov",
    }
    base.update(kwargs)
    return base


# ── 1. delivery_end_date в прошлом → не GOLD ──────────────────────────────────

def test_gold_requires_delivery_not_expired():
    card = _card(delivery_end_date=PAST)
    level, reasons = score_awarded(card, category_median=4_000_000, today=TODAY)
    assert level == AwardedLevel.OUT_OF_PROFILE
    assert "delivery_expired" in reasons


# ── 2. < 30 дней до окончания → не GOLD ──────────────────────────────────────

def test_gold_requires_sufficient_time():
    card = _card(delivery_end_date=FUTURE_20)
    level, reasons = score_awarded(card, category_median=4_000_000, today=TODAY)
    assert level != AwardedLevel.GOLD


# ── 3. нет evidence → не GOLD ────────────────────────────────────────────────

def test_gold_requires_evidence():
    card = _card(evidence_count=0, match_count=0)
    level, reasons = score_awarded(card, category_median=4_000_000, today=TODAY)
    assert level != AwardedLevel.GOLD
    assert "no_evidence" in reasons


# ── 4. выше медианы → GOLD, ниже → SILVER (при прочих равных) ────────────────

def test_gold_above_median_beats_silver_below_median():
    base = dict(
        delivery_end_date=FUTURE_60,
        evidence_count=5,
        match_count=3,
        contractor_name="ООО Победитель",
        crm_category="computers",
        okpd_code="26.20.11",
        object_type="компьютеры",
        source_table="zakupki_gov",
    )
    card_high = dict(base, initial_price=10_000_000)
    card_low  = dict(base, initial_price=2_000_000)
    median = 8_000_000

    level_high, _ = score_awarded(card_high, category_median=median, today=TODAY)
    level_low, _  = score_awarded(card_low,  category_median=median, today=TODAY)

    assert level_high == AwardedLevel.GOLD
    assert level_low  != AwardedLevel.GOLD


# ── 5. нет дат → NEEDS_REVIEW ────────────────────────────────────────────────

def test_needs_review_when_no_delivery_date():
    card = _card(delivery_end_date=None, execution_end_at=None)
    level, reasons = score_awarded(card, today=TODAY)
    assert level == AwardedLevel.NEEDS_REVIEW
    assert "no_delivery_date" in reasons


# ── 6. большая сумма без evidence → не GOLD ──────────────────────────────────

def test_no_artificial_gold_for_high_price_only():
    card = _card(
        initial_price=100_000_000,
        evidence_count=0,
        match_count=0,
    )
    level, reasons = score_awarded(card, category_median=5_000_000, today=TODAY)
    assert level != AwardedLevel.GOLD


# ── 7. истёкший контракт → OUT_OF_PROFILE ────────────────────────────────────

def test_out_of_profile_for_expired_contracts():
    card = _card(delivery_end_date=PAST)
    level, _ = score_awarded(card, today=TODAY)
    assert level == AwardedLevel.OUT_OF_PROFILE


# ── 8. cohort из 2 объектов → медиана не учитывается ─────────────────────────

def test_cohort_median_requires_3_objects():
    cards = [
        {"initial_price": 1_000_000, "crm_category": "A", "okpd_code": "10.1", "source_table": "t"},
        {"initial_price": 2_000_000, "crm_category": "A", "okpd_code": "10.1", "source_table": "t"},
    ]
    medians = compute_cohort_medians(cards)
    assert ("A", "10", "t") not in medians


# ── 9. сортировка GOLD первым ─────────────────────────────────────────────────

def test_sort_order_gold_first():
    cards = [
        {"awarded_level": "NEEDS_REVIEW", "_days_to_delivery": 20},
        {"awarded_level": "GOLD",         "_days_to_delivery": 60},
        {"awarded_level": "SILVER",       "_days_to_delivery": 30},
        {"awarded_level": "BRONZE",       "_days_to_delivery": 10},
        {"awarded_level": "WOOD",         "_days_to_delivery": 3},
    ]
    sorted_cards = sorted(cards, key=awarded_sort_key)
    levels = [c["awarded_level"] for c in sorted_cards]
    assert levels[0] == "GOLD"
    assert levels[1] == "SILVER"
    assert levels[2] == "BRONZE"
    assert levels[-1] == "WOOD"


# ── 10. 3 дня до окончания → WOOD ────────────────────────────────────────────

def test_wood_for_nearly_closed_window():
    card = _card(delivery_end_date=FUTURE_3)
    level, reasons = score_awarded(card, today=TODAY)
    assert level == AwardedLevel.WOOD
    assert any("window_nearly_closed" in r for r in reasons)


# ── 11. computers — проектировщик не нужен, прямая поставка ──────────────────

def test_computers_no_designer_needed():
    card = _card(
        object_type="компьютеры",
        okpd_code="26.20.11",
        crm_category="компьютеры",
        delivery_end_date=FUTURE_60,
        evidence_count=5,
        contractor_name="ООО ИТ-Поставщик",
        initial_price=5_000_000,
    )
    level, reasons = score_awarded(card, category_median=4_000_000, today=TODAY)
    assert level == AwardedLevel.GOLD
    assert "computers_direct_supply_ok" in reasons


# ── 12. частичный evidence → SILVER ──────────────────────────────────────────

def test_silver_partial_evidence():
    # Evidence есть, но нет победителя и срок < 30 дней
    card = _card(
        delivery_end_date=FUTURE_20,
        evidence_count=3,
        contractor_name="",  # нет победителя
        initial_price=5_000_000,
    )
    level, reasons = score_awarded(card, category_median=4_000_000, today=TODAY)
    assert level == AwardedLevel.SILVER
