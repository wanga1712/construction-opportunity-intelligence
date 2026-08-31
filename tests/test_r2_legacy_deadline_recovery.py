"""Unit and integration tests for R2 legacy deadline recovery rules."""
from __future__ import annotations

import pytest
from datetime import datetime, date
from typing import Any, Dict

from src.services.commercial_routing_v3.projection_writer import _upsert_one
from src.services.torgi_publication import source_lifecycle_allows_torgi


class MockCrmDb:
    def __init__(self) -> None:
        self.updates = []

    def execute_update(self, query: str, params: Dict[str, Any]) -> None:
        self.updates.append((query, params))


def test_44fz_normal_path() -> None:
    crm_db = MockCrmDb()
    row = {
        "source_table": "reestr_contract_44_fz",
        "source_id": 12345,
        "contract_number": "44-CN-1",
        "auction_name": "Test 44-FZ",
        "start_date": "2026-08-01",
        "end_date": "2026-08-10",
        "initial_price": 1000.0,
    }
    action = _upsert_one(crm_db, row, existing=None, dry_run=False)
    assert action == "insert"
    assert len(crm_db.updates) == 1
    params = crm_db.updates[0][1]
    assert params["deadline_trust"] == "TRUSTED"
    assert params["end_date"] == "2026-08-10"


def test_current_223fz_normal_path() -> None:
    crm_db = MockCrmDb()
    row = {
        "source_table": "reestr_contract_223_fz",
        "source_id": 23456,
        "contract_number": "223-CN-CURRENT",
        "auction_name": "Test 223-FZ New",
        "start_date": "2026-08-20",
        "end_date": "2026-08-30",
        "source_created_at": "2026-08-20 10:00:00",
        "source_updated_at": "2026-08-20 12:00:00",
    }
    action = _upsert_one(crm_db, row, existing=None, dry_run=False)
    assert action == "insert"
    assert len(crm_db.updates) == 1
    params = crm_db.updates[0][1]
    assert params["deadline_trust"] == "TRUSTED"
    assert params["end_date"] == "2026-08-30"


def test_recovered_legacy_223fz() -> None:
    crm_db = MockCrmDb()
    row = {
        "source_table": "reestr_contract_223_fz",
        "source_id": 34567,
        "contract_number": "223-CN-LEGACY-RECOVERED",
        "auction_name": "Test 223-FZ Legacy Recovered",
        "start_date": "2026-08-01",
        "end_date": "2026-08-06",
        "source_created_at": "2026-08-05 10:00:00",  # legacy (before 2026-08-16)
        "source_updated_at": "2026-08-20 12:00:00",  # repaired today (after 2026-08-16)
    }
    action = _upsert_one(crm_db, row, existing=None, dry_run=False)
    assert action == "insert"
    params = crm_db.updates[0][1]
    assert params["deadline_trust"] == "RECOVERED"
    assert params["end_date"] == "2026-08-06"


def test_unrecoverable_legacy_223fz() -> None:
    crm_db = MockCrmDb()
    row = {
        "source_table": "reestr_contract_223_fz",
        "source_id": 45678,
        "contract_number": "223-CN-LEGACY-UNRECOVERED",
        "auction_name": "Test 223-FZ Legacy Unrecovered",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",                  # this end_date is the invalid execution end date
        "source_created_at": "2026-08-05 10:00:00",  # legacy (before 2026-08-16)
        "source_updated_at": "2026-08-05 10:00:00",  # not repaired (before 2026-08-16)
    }
    action = _upsert_one(crm_db, row, existing=None, dry_run=False)
    assert action == "insert"
    params = crm_db.updates[0][1]
    assert params["deadline_trust"] == "UNRECOVERABLE_LEGACY"
    # The invalid execution date MUST NOT become the tender deadline (set to NULL)
    assert params["end_date"] is None
    # Verify execution_start (start_date) cannot become application deadline either
    assert params["end_date"] != params["start_date"]


def test_unrecoverable_legacy_cannot_appear_as_active() -> None:
    # Set crm_stage = 'torgi', award_status = 'submission_closed_waiting_award', end_date = None
    # according to the legacy unrecoverable lifecycle mapping.
    # Assert this row is NOT allowed in active/open "Идут торги" workset.
    allowed = source_lifecycle_allows_torgi(
        crm_stage="torgi",
        award_status="submission_closed_waiting_award",
        end_date=None,
        today=date(2026, 8, 31)
    )
    assert allowed is False


def test_deadline_trust_always_initialized() -> None:
    # We test that all paths return a payload with non-None deadline_trust in ('TRUSTED', 'RECOVERED', 'UNRECOVERABLE_LEGACY')
    crm_db = MockCrmDb()
    
    # Path 1: 44-FZ
    _upsert_one(crm_db, {"source_table": "reestr_contract_44_fz", "source_id": 1}, None, False)
    assert crm_db.updates[-1][1]["deadline_trust"] in ("TRUSTED", "RECOVERED", "UNRECOVERABLE_LEGACY")

    # Path 2: current 223-FZ
    _upsert_one(crm_db, {"source_table": "reestr_contract_223_fz", "source_id": 2, "source_created_at": "2026-08-20"}, None, False)
    assert crm_db.updates[-1][1]["deadline_trust"] in ("TRUSTED", "RECOVERED", "UNRECOVERABLE_LEGACY")

    # Path 3: recovered legacy 223-FZ
    _upsert_one(crm_db, {
        "source_table": "reestr_contract_223_fz",
        "source_id": 3,
        "source_created_at": "2026-08-01",
        "source_updated_at": "2026-08-20",
    }, None, False)
    assert crm_db.updates[-1][1]["deadline_trust"] in ("TRUSTED", "RECOVERED", "UNRECOVERABLE_LEGACY")

    # Path 4: unrecoverable legacy 223-FZ
    _upsert_one(crm_db, {
        "source_table": "reestr_contract_223_fz",
        "source_id": 4,
        "source_created_at": "2026-08-01",
        "source_updated_at": "2026-08-01",
    }, None, False)
    assert crm_db.updates[-1][1]["deadline_trust"] in ("TRUSTED", "RECOVERED", "UNRECOVERABLE_LEGACY")
