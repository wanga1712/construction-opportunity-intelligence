from datetime import date, datetime, timezone
from pathlib import Path
from src.services.commercial_routing_v3.submission_window import (
    MIN_REMAINING_SUBMISSION_DAYS, actionable_submission_sql,
    is_actionable_submission_window,
)

def test_date_window_today_tomorrow_excluded_two_days_included():
    today=date(2026,8,23)
    assert MIN_REMAINING_SUBMISSION_DAYS == 2
    assert not is_actionable_submission_window(date(2026,8,23),today=today)
    assert not is_actionable_submission_window(date(2026,8,24),today=today)
    assert is_actionable_submission_window(date(2026,8,25),today=today)

def test_exact_datetime_uses_real_remaining_duration():
    now=datetime(2026,8,23,12,tzinfo=timezone.utc)
    assert not is_actionable_submission_window(datetime(2026,8,25,11,tzinfo=timezone.utc),now=now)
    assert is_actionable_submission_window(datetime(2026,8,25,12,tzinfo=timezone.utc),now=now)

def test_sql_authority_comes_from_same_constant():
    assert "INTERVAL '2 days'" in actionable_submission_sql("cp")

def test_no_old_open_sql_in_authoritative_consumers():
    root=Path(__file__).parents[1]/"src"
    for rel in ("ui/components/analytics_v2/tabs.py","services/annotation_queue_service.py"):
        assert "end_date >= CURRENT_DATE" not in (root/rel).read_text(encoding="utf-8")
