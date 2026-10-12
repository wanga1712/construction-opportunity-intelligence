"""Synthetic acceptance for the table workspace temporal policy + layouts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.analytics_table_workspace_service import (
    ALL_MODES,
    DIRECT_SUPPLY,
    EMBEDDED_MATERIAL,
    build_workspace_rows,
    layout_for,
)
from src.services.commercial_routing_v3.submission_window_temporal import (
    BRONZE_CAP,
    EXPIRED,
    FRESH,
    SILVER_CAP,
    TEMPORAL_UNKNOWN,
    WOOD_CAP,
    bucket_for_consumed_ratio,
    compute_submission_window,
    next_degrade,
)
from src.services.effective_medal_service import calculate_decay_steps

START = "2026-01-01"
DEADLINE = "2026-01-21"  # 20-day window


def _now(fraction: float) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=20 * fraction)


def _window(medal: str, fraction: float = 0.20):
    return compute_submission_window(
        submission_start_at=START,
        submission_deadline_at=DEADLINE,
        baseline_medal=medal,
        now=_now(fraction),
    )


def test_bucket_thresholds_are_exact():
    assert bucket_for_consumed_ratio(0.20) == FRESH
    assert bucket_for_consumed_ratio(0.40) == SILVER_CAP
    assert bucket_for_consumed_ratio(0.50) == SILVER_CAP
    assert bucket_for_consumed_ratio(0.60) == BRONZE_CAP
    assert bucket_for_consumed_ratio(0.70) == BRONZE_CAP
    assert bucket_for_consumed_ratio(0.80) == WOOD_CAP
    assert bucket_for_consumed_ratio(0.99) == WOOD_CAP
    assert bucket_for_consumed_ratio(1.00) == EXPIRED


def test_gold_next_degrade_relative_to_bucket():
    assert _window("GOLD", 0.20)["temporal_bucket"] == FRESH
    assert next_degrade("GOLD", 0.20) == ("SILVER", 0.40)

    assert _window("GOLD", 0.50)["temporal_bucket"] == SILVER_CAP
    assert next_degrade("GOLD", 0.50) == ("BRONZE", 0.60)

    assert _window("GOLD", 0.70)["temporal_bucket"] == BRONZE_CAP
    assert next_degrade("GOLD", 0.70) == ("WOOD", 0.80)

    assert _window("GOLD", 0.85)["temporal_bucket"] == WOOD_CAP
    assert next_degrade("GOLD", 0.85) is None


def test_lower_baselines_skip_non_downgrading_caps():
    # SILVER is not downgraded by the SILVER cap; its next real downgrade is BRONZE.
    assert next_degrade("SILVER", 0.20) == ("BRONZE", 0.60)
    # BRONZE skips SILVER/BRONZE caps; only WOOD downgrades it.
    assert next_degrade("BRONZE", 0.20) == ("WOOD", 0.80)
    # WOOD has no further temporal downgrade.
    assert next_degrade("WOOD", 0.20) is None


def test_seconds_to_wood_and_next_degrade():
    view = _window("GOLD", 0.20)
    assert view["seconds_to_wood"] is not None and view["seconds_to_wood"] > 0
    assert view["seconds_to_next_degrade"] is not None
    assert view["seconds_to_next_degrade"] < view["seconds_to_wood"]
    # ratio already past the WOOD cap -> no time left to WOOD
    assert _window("GOLD", 0.85)["seconds_to_wood"] == 0


def test_temporal_unknown_missing_or_inverted():
    missing = compute_submission_window(submission_start_at=None, submission_deadline_at=None)
    assert missing["temporal_state"] == "UNKNOWN"
    assert missing["temporal_bucket"] == TEMPORAL_UNKNOWN
    assert missing["window_consumed_ratio"] is None

    inverted = compute_submission_window(
        submission_start_at="2026-01-10", submission_deadline_at="2026-01-05", now=_now(0.1)
    )
    assert inverted["temporal_bucket"] == TEMPORAL_UNKNOWN


def test_expired_state():
    view = compute_submission_window(
        submission_start_at=START, submission_deadline_at=DEADLINE, now=_now(1.5)
    )
    assert view["temporal_state"] == "EXPIRED"
    assert view["temporal_bucket"] == EXPIRED


def test_direct_supply_columns_and_none_rendering():
    raw = {
        "procurement_id": 1,
        "opportunity_track": "DIRECT_SUPPLY",
        "auction_name": "Поставка серверного оборудования",
        "contract_number": "03731000001",
        "initial_price": 56_300_000,
        "customer": "АО Рос",
        "delivery_region": "Москва",
        "crm_stage": "torgi",
        "source_table": "tender_44",
        "subcategory_name": "Серверы",
        "object_type": None,
        "object_context": None,
        "candidate_initial_medal": "GOLD",
        "current_effective_medal": "GOLD",
        "submission_start_at": START,
        "submission_deadline_at": DEADLINE,
    }
    result = build_workspace_rows([raw], selected_mode=DIRECT_SUPPLY, now=_now(0.20))
    assert "object" not in result["columns"] and "works" not in result["columns"]
    row = result["rows"][0]
    assert row["customer"] == "АО Рос"
    assert row["product_primary"] == "Серверы" and row["product_secondary"] is None
    assert row["object_text"] == "—" and row["works_text"] == "—"
    assert row["temporal"]["temporal_bucket"] == FRESH


def test_zero_and_null_price_render_as_dash():
    base = {
        "procurement_id": 2, "opportunity_track": "DIRECT_SUPPLY", "auction_name": "X",
        "crm_stage": "torgi", "subcategory_name": "Y", "initial_price": 0,
        "candidate_initial_medal": "SILVER", "current_effective_medal": "SILVER",
    }
    row = build_workspace_rows([base], now=_now(0.5))["rows"][0]
    assert row["price_text"] == "—"
    assert row["customer"] == "—"
    # subcategory is never duplicated into the product column
    assert row["product_secondary"] is None


def test_mixed_layout_uses_single_context_column():
    mixed = layout_for(ALL_MODES)
    assert "context" in mixed and "object" not in mixed and "works" not in mixed
    embedded = layout_for(EMBEDDED_MATERIAL)
    assert "object" in embedded and "works" in embedded and "context" not in embedded


def test_deadline_only_fallback_matches_medal_decay_schedule():
    # Lock our day boundaries to the canonical medal decay schedule.
    assert calculate_decay_steps(14.5) == 0 and calculate_decay_steps(14.0) == 1
    assert calculate_decay_steps(7.5) == 1 and calculate_decay_steps(7.0) == 2
    assert calculate_decay_steps(3.5) == 2 and calculate_decay_steps(3.0) == 3

    cases = [(20, FRESH), (10, SILVER_CAP), (5, BRONZE_CAP), (1, WOOD_CAP)]
    for days, expected in cases:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        view = compute_submission_window(
            submission_start_at=None,
            submission_deadline_at=now + timedelta(days=days),
            baseline_medal="GOLD",
            now=now,
        )
        assert view["temporal_bucket"] == expected, (days, view)
        assert view["window_basis"] == "DEADLINE_ONLY"
        assert view["window_consumed_ratio"] is None


def test_deadline_only_next_degrade_relative_to_baseline():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert compute_submission_window(
        submission_start_at=None, submission_deadline_at=now + timedelta(days=10),
        baseline_medal="GOLD", now=now)["next_degrade_medal"] == "BRONZE"
    assert compute_submission_window(
        submission_start_at=None, submission_deadline_at=now + timedelta(days=10),
        baseline_medal="SILVER", now=now)["next_degrade_medal"] == "BRONZE"
    assert compute_submission_window(
        submission_start_at=None, submission_deadline_at=now + timedelta(days=10),
        baseline_medal="BRONZE", now=now)["next_degrade_medal"] == "WOOD"


def test_deadline_only_expired_and_past_not_ratio():
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    view = compute_submission_window(
        submission_start_at=None, submission_deadline_at=now - timedelta(days=1), baseline_medal="GOLD", now=now
    )
    assert view["temporal_bucket"] == EXPIRED
