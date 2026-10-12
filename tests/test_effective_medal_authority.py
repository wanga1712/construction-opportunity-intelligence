"""Unit tests for Authority Hierarchy in Effective Medal Service.

Authority order:
EXPERT > SECOND_PASS_MODEL > PRELIMINARY > UNASSESSED
"""
from datetime import datetime, timezone, timedelta
import pytest

from src.services.effective_medal_service import (
    resolve_card_effective_medals,
    compute_effective_medal,
    calculate_decay_steps,
    calculate_days_to_deadline,
)


def test_authority_hierarchy_expert_wins():
    """Expert confirmed medal overrides both model and preliminary."""
    card = {
        "id": 1,
        "is_confirmed": True,
        "expert_medal": "GOLD",
        "model_medal": "SILVER",
        "model_score": 75,
        "preliminary_medal": "BRONZE",
        "priority_score": 60,
        "end_date": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
    }
    res = resolve_card_effective_medals(card)
    assert res["base_medal"] == "GOLD"
    assert res["base_medal_authority"] == "EXPERT"
    assert res["effective_medal"] == "GOLD"
    assert res["expert_medal"] == "GOLD"
    assert res["model_medal"] == "SILVER"
    assert res["preliminary_medal"] == "BRONZE"


def test_authority_hierarchy_model_wins_over_preliminary():
    """When expert is not confirmed, Second Pass model medal overrides preliminary."""
    card = {
        "id": 2,
        "is_confirmed": False,
        "expert_medal": None,
        "model_medal": "SILVER",
        "model_score": 80,
        "preliminary_medal": "BRONZE",
        "priority_score": 50,
        "end_date": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
    }
    res = resolve_card_effective_medals(card)
    assert res["base_medal"] == "SILVER"
    assert res["base_medal_authority"] == "SECOND_PASS_MODEL"
    assert res["effective_medal"] == "SILVER"


def test_authority_hierarchy_preliminary_fallback():
    """When expert and model are absent, preliminary First Pass medal is used."""
    card = {
        "id": 3,
        "is_confirmed": False,
        "expert_medal": None,
        "model_medal": None,
        "preliminary_medal": "BRONZE",
        "priority_score": 50,
        "end_date": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
    }
    res = resolve_card_effective_medals(card)
    assert res["base_medal"] == "BRONZE"
    assert res["base_medal_authority"] == "PRELIMINARY"
    assert res["effective_medal"] == "BRONZE"


def test_authority_hierarchy_unassessed():
    """When no evaluations exist, base is UNASSESSED."""
    card = {
        "id": 4,
        "is_confirmed": False,
        "expert_medal": None,
        "model_medal": None,
        "preliminary_medal": "UNASSESSED",
        "end_date": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
    }
    res = resolve_card_effective_medals(card)
    assert res["base_medal"] == "UNASSESSED"
    assert res["base_medal_authority"] == "UNASSESSED"
    assert res["effective_medal"] == "UNASSESSED"


def test_authority_hierarchy_with_deadline_decay():
    """Effective medal applies time decay on the model-selected base medal."""
    # Model GOLD with 5 days left -> decay 2 steps (GOLD -> SILVER -> BRONZE)
    card = {
        "id": 5,
        "is_confirmed": False,
        "model_medal": "GOLD",
        "preliminary_medal": "SILVER",
        "end_date": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
    }
    res = resolve_card_effective_medals(card)
    assert res["base_medal"] == "GOLD"
    assert res["base_medal_authority"] == "SECOND_PASS_MODEL"
    assert res["deadline_decay_steps"] == 2
    assert res["effective_medal"] == "BRONZE"
    assert res["model_medal"] == "GOLD"  # Source remains immutable
