"""Unit tests for Effective Medal Time Decay Service (Phase 3.2)."""
from datetime import datetime, timezone
import pytest

from src.services.effective_medal_service import (
    calculate_days_to_deadline,
    calculate_decay_steps,
    compute_effective_medal,
    resolve_card_effective_medals,
)


def test_decay_schedule():
    # > 14 days: 0 steps
    assert calculate_decay_steps(20.0) == 0
    assert calculate_decay_steps(14.1) == 0

    # 8 .. 14 days: 1 step
    assert calculate_decay_steps(14.0) == 1
    assert calculate_decay_steps(10.0) == 1
    assert calculate_decay_steps(8.0) == 1
    assert calculate_decay_steps(7.5) == 1

    # 4 .. 7 days: 2 steps
    assert calculate_decay_steps(7.0) == 2
    assert calculate_decay_steps(5.0) == 2
    assert calculate_decay_steps(4.0) == 2
    assert calculate_decay_steps(3.5) == 2

    # 2 .. 3 days: 3 steps
    assert calculate_decay_steps(3.0) == 3
    assert calculate_decay_steps(2.5) == 3
    assert calculate_decay_steps(2.0) == 3

    # 0 .. <2 days: forced wood (step=4)
    assert calculate_decay_steps(1.9) == 4
    assert calculate_decay_steps(0.5) == 4
    assert calculate_decay_steps(0.0) == 4

    # < 0 days: closed
    assert calculate_decay_steps(-0.1) == 99
    assert calculate_decay_steps(-5.0) == 99


def test_gold_decay_transitions():
    assert compute_effective_medal("GOLD", 20.0) == ("GOLD", 1, 0)
    assert compute_effective_medal("GOLD", 10.0) == ("SILVER", 2, 1)
    assert compute_effective_medal("GOLD", 5.0) == ("BRONZE", 3, 2)
    assert compute_effective_medal("GOLD", 2.5) == ("WOOD", 4, 3)
    assert compute_effective_medal("GOLD", 1.0) == ("WOOD", 4, 4)
    assert compute_effective_medal("GOLD", -1.0) == ("CLOSED", 6, 99)


def test_silver_decay_transitions():
    assert compute_effective_medal("SILVER", 20.0) == ("SILVER", 2, 0)
    assert compute_effective_medal("SILVER", 10.0) == ("BRONZE", 3, 1)
    assert compute_effective_medal("SILVER", 5.0) == ("WOOD", 4, 2)
    assert compute_effective_medal("SILVER", 2.5) == ("WOOD", 4, 3)
    assert compute_effective_medal("SILVER", 1.0) == ("WOOD", 4, 4)
    assert compute_effective_medal("SILVER", -1.0) == ("CLOSED", 6, 99)


def test_bronze_decay_transitions():
    assert compute_effective_medal("BRONZE", 20.0) == ("BRONZE", 3, 0)
    assert compute_effective_medal("BRONZE", 10.0) == ("WOOD", 4, 1)
    assert compute_effective_medal("BRONZE", 5.0) == ("WOOD", 4, 2)
    assert compute_effective_medal("BRONZE", -1.0) == ("CLOSED", 6, 99)


def test_wood_and_unassessed():
    assert compute_effective_medal("WOOD", 20.0) == ("WOOD", 4, 0)
    assert compute_effective_medal("WOOD", 5.0) == ("WOOD", 4, 2)
    assert compute_effective_medal("WOOD", -1.0) == ("CLOSED", 6, 99)

    assert compute_effective_medal("UNASSESSED", 20.0) == ("UNASSESSED", 5, 0)
    assert compute_effective_medal("UNASSESSED", -1.0) == ("CLOSED", 6, 99)


def test_source_medals_immutability():
    original_card = {
        "id": 101,
        "preliminary_medal": "GOLD",
        "candidate_medal": "GOLD",
        "expert_medal": "SILVER",
        "is_confirmed": False,
        "end_date": "2026-10-01T12:00:00Z",
    }
    # Fix now to be 2026-09-26 (5 days left -> decay 2 steps -> BRONZE)
    now = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
    card_copy = dict(original_card)

    res = resolve_card_effective_medals(card_copy, now=now)

    # Immutable source fields preserved
    assert res["preliminary_medal"] == "GOLD"
    assert res["candidate_medal"] == "GOLD"
    assert res["expert_medal"] == "SILVER"

    # Effective fields computed
    assert res["base_medal"] == "GOLD"
    assert res["base_medal_authority"] == "PRELIMINARY"
    assert res["effective_medal"] == "BRONZE"
    assert res["effective_medal_rank"] == 3
    assert res["deadline_decay_steps"] == 2


def test_expert_base_medal_authority():
    card = {
        "id": 102,
        "preliminary_medal": "BRONZE",
        "candidate_medal": "BRONZE",
        "expert_medal": "GOLD",
        "is_confirmed": True,
        "end_date": "2026-10-01T12:00:00Z",
    }
    # 5 days left -> base=GOLD -> decay 2 steps -> BRONZE
    now = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
    res = resolve_card_effective_medals(card, now=now)

    assert res["base_medal"] == "GOLD"
    assert res["base_medal_authority"] == "EXPERT"
    assert res["effective_medal"] == "BRONZE"
    assert res["effective_medal_rank"] == 3
