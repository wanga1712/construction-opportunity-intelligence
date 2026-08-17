"""Tests for commercial_timing_value V1 (not deadline_pressure)."""
from __future__ import annotations

from datetime import date

from src.services.commercial_routing_v3.commercial_timing import (
    compute_active_commercial_timing,
    compute_awarded_commercial_timing,
)


def test_active_ending_today_low_timing_even_if_urgent():
    as_of = date(2026, 8, 14)
    # started long ago, ends today
    old = compute_active_commercial_timing(
        procurement_start_at="2026-06-01",
        procurement_end_at="2026-08-14",
        published_at_provenance="SOURCE_NOT_AVAILABLE",
        as_of=as_of,
    )
    # recent start, ~10 days remaining
    fresh = compute_active_commercial_timing(
        procurement_start_at="2026-08-10",
        procurement_end_at="2026-08-24",
        published_at_provenance="SOURCE_NOT_AVAILABLE",
        as_of=as_of,
    )
    assert old["remaining_days"] == 0
    assert old["commercial_timing_value"] < fresh["commercial_timing_value"]
    assert old["commercial_timing_value"] < 20


def test_active_negative_remaining_zeroish():
    as_of = date(2026, 8, 14)
    t = compute_active_commercial_timing(
        procurement_start_at="2026-07-01",
        procurement_end_at="2026-08-10",
        published_at_provenance="SOURCE_NOT_AVAILABLE",
        as_of=as_of,
    )
    assert t["remaining_days"] < 0
    assert t["commercial_timing_value"] == 0


def test_awarded_prefers_recent_award_with_runway():
    as_of = date(2026, 8, 14)
    stale = compute_awarded_commercial_timing(
        award_at="2025-01-01",
        delivery_start_at="2025-02-01",
        delivery_end_at="2026-08-14",
        as_of=as_of,
    )
    fresh = compute_awarded_commercial_timing(
        award_at="2026-08-01",
        delivery_start_at="2026-08-10",
        delivery_end_at="2026-11-01",
        as_of=as_of,
    )
    assert fresh["commercial_timing_value"] > stale["commercial_timing_value"]
