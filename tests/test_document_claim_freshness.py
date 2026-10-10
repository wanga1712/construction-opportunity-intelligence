from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.commercial_routing_v3.claim_freshness import (  # noqa: E402
    TIER_BACKLOG,
    TIER_CHANGED,
    TIER_FRESH,
    compute_work_tier,
)

TODAY = date(2026, 10, 10)


def test_fresh_open_procurement_is_tier0():
    proc = {
        "start_date": "2026-10-08",
        "end_date": "2026-10-15",
        "crm_stage": "torgi",
        "award_status": "submission_open",
    }
    assert compute_work_tier(proc, today=TODAY) == TIER_FRESH


def test_old_but_still_open_procurement_is_tier1():
    proc = {
        "start_date": "2026-09-23",
        "end_date": "2026-10-12",
        "crm_stage": "torgi",
        "award_status": "submission_open",
    }
    assert compute_work_tier(proc, today=TODAY) == TIER_CHANGED


def test_awarded_live_project_is_tier1():
    proc = {
        "start_date": "2026-08-01",
        "end_date": "2026-10-20",
        "crm_stage": "awarded",
        "award_status": "awarded",
    }
    assert compute_work_tier(proc, today=TODAY) == TIER_CHANGED


def test_closed_or_expired_procurement_is_backlog():
    proc = {
        "start_date": "2026-09-21",
        "end_date": "2026-09-30",
        "crm_stage": "torgi",
        "award_status": "submission_open",
    }
    assert compute_work_tier(proc, today=TODAY) == TIER_BACKLOG


def test_claim_order_puts_freshness_before_queue_id():
    paths = [
        ROOT / "tender_documents_research" / "document_processor" / "backends" / "queue_repository.py",
        ROOT / "src" / "services" / "queue_repository.py",
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "q.work_tier ASC" in source
        assert "q.source_start_date DESC NULLS LAST" in source
        assert "q.id DESC" in source
        assert "q.id ASC" not in source
