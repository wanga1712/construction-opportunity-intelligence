from __future__ import annotations

from datetime import datetime

from src.domain.commercial_opportunity_lifecycle import (
    CommercialOpportunityState,
    SourceLifecycleEvent,
)
from src.services.commercial_routing_v3.opportunity_lifecycle_sync import (
    compute_opportunity_lifecycle_updates,
    sync_opportunities_lifecycle,
)


def _ts() -> datetime:
    return datetime(2026, 8, 12, 10, 0, 0)


class TestOpportunityLifecycleTransitions:
    def test_direct_supply_open_active(self) -> None:
        updated, audit = compute_opportunity_lifecycle_updates(
            source_procurements=[
                {
                    "procurement_id": 1,
                    "source_table": "reestr_contract_44_fz",
                    "contract_number": "CN-1",
                    "crm_stage": "torgi",
                    "award_status": "submission_open",
                }
            ],
            opportunities=[
                {
                    "id": 10,
                    "procurement_id": 1,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "WAITING_SOURCE_OUTCOME",
                    "last_source_event": "WAITING_SOURCE_OUTCOME",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                }
            ],
            existing_audit=[],
            now=_ts(),
        )
        assert updated[0]["commercial_state"] == CommercialOpportunityState.ACTIVE.value
        assert updated[0]["last_source_event"] == SourceLifecycleEvent.OPEN.value
        assert len(audit) == 1

    def test_direct_supply_awarded_closed(self) -> None:
        updated, audit = compute_opportunity_lifecycle_updates(
            source_procurements=[
                {
                    "procurement_id": 1,
                    "source_table": "reestr_contract_44_fz_awarded",
                    "contract_number": "CN-2",
                    "crm_stage": "razygranye",
                    "award_status": "awarded",
                }
            ],
            opportunities=[
                {
                    "id": 11,
                    "procurement_id": 1,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                }
            ],
            existing_audit=[],
            now=_ts(),
        )
        assert updated[0]["commercial_state"] == CommercialOpportunityState.CLOSED.value
        assert updated[0]["last_source_event"] == SourceLifecycleEvent.AWARDED.value
        assert audit[0]["reason"] == "DIRECT_SUPPLY_CLOSED"

    def test_embedded_followup_on_awarded(self) -> None:
        updated, audit = compute_opportunity_lifecycle_updates(
            source_procurements=[
                {
                    "procurement_id": 2,
                    "source_table": "reestr_contract_44_fz_awarded",
                    "contract_number": "CN-3",
                    "crm_stage": "razygranye",
                    "award_status": "awarded",
                }
            ],
            opportunities=[
                {
                    "id": 12,
                    "procurement_id": 2,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "EMBEDDED_MATERIAL",
                    "commercial_state": "WAITING_SOURCE_OUTCOME",
                    "last_source_event": "WAITING_SOURCE_OUTCOME",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                }
            ],
            existing_audit=[],
            now=_ts(),
        )
        assert updated[0]["commercial_state"] == CommercialOpportunityState.FOLLOW_UP_AWARDED.value
        assert audit[0]["reason"] == "FOLLOWUP_AWARDED"

    def test_mixed_opportunities_container_survives(self) -> None:
        updated, _ = compute_opportunity_lifecycle_updates(
            source_procurements=[
                {
                    "procurement_id": 3,
                    "source_table": "reestr_contract_44_fz_awarded",
                    "contract_number": "CN-4",
                    "crm_stage": "razygranye",
                    "award_status": "awarded",
                }
            ],
            opportunities=[
                {
                    "id": 13,
                    "procurement_id": 3,
                    "commercial_category_code": "computers",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                },
                {
                    "id": 14,
                    "procurement_id": 3,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "EMBEDDED_MATERIAL",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                },
            ],
            existing_audit=[],
            now=_ts(),
        )
        by_id = {o["id"]: o for o in updated}
        assert by_id[13]["commercial_state"] == CommercialOpportunityState.CLOSED.value
        assert by_id[14]["commercial_state"] == CommercialOpportunityState.FOLLOW_UP_AWARDED.value

    def test_duplicate_procurement_suppresses_open_when_awarded_dominant(self) -> None:
        updated, audit = compute_opportunity_lifecycle_updates(
            source_procurements=[
                {
                    "procurement_id": 100,
                    "source_table": "reestr_contract_44_fz",
                    "contract_number": "CN-5",
                    "crm_stage": "torgi",
                    "award_status": "submission_open",
                },
                {
                    "procurement_id": 101,
                    "source_table": "reestr_contract_44_fz_awarded",
                    "contract_number": "CN-5",
                    "crm_stage": "razygranye",
                    "award_status": "awarded",
                },
            ],
            opportunities=[
                {
                    "id": 15,
                    "procurement_id": 100,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                },
                {
                    "id": 16,
                    "procurement_id": 101,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                },
            ],
            existing_audit=[],
            now=_ts(),
        )
        by_id = {o["id"]: o for o in updated}
        assert by_id[15]["commercial_state"] == CommercialOpportunityState.STALE_SOURCE.value
        assert by_id[16]["commercial_state"] == CommercialOpportunityState.CLOSED.value
        assert any(a["reason"] == "S7_DUPLICATE_SUPPRESSED" for a in audit)

    def test_temp_missing_source_does_not_archive(self) -> None:
        updated, audit = compute_opportunity_lifecycle_updates(
            source_procurements=[],
            opportunities=[
                {
                    "id": 17,
                    "procurement_id": 999,
                    "contract_number": "CN-missing",
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                }
            ],
            existing_audit=[],
            now=_ts(),
        )
        assert updated[0]["commercial_state"] == CommercialOpportunityState.ACTIVE.value
        assert updated[0]["source_sync_status"] == "MISSING"
        assert updated[0]["source_missing_since"] is not None
        assert audit == []

    def test_idempotence_no_duplicate_audit(self) -> None:
        existing_audit = [
            {
                "opportunity_id": 20,
                "old_commercial_state": CommercialOpportunityState.ACTIVE.value,
                "new_commercial_state": CommercialOpportunityState.CLOSED.value,
                "old_source_event": SourceLifecycleEvent.OPEN.value,
                "new_source_event": SourceLifecycleEvent.AWARDED.value,
                "reason": "DIRECT_SUPPLY_CLOSED",
            }
        ]
        updated, audit = compute_opportunity_lifecycle_updates(
            source_procurements=[
                {
                    "procurement_id": 200,
                    "source_table": "reestr_contract_44_fz_awarded",
                    "contract_number": "CN-6",
                    "crm_stage": "razygranye",
                    "award_status": "awarded",
                }
            ],
            opportunities=[
                {
                    "id": 20,
                    "procurement_id": 200,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": CommercialOpportunityState.ACTIVE.value,
                    "last_source_event": SourceLifecycleEvent.OPEN.value,
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                }
            ],
            existing_audit=existing_audit,
            now=_ts(),
        )
        # State still computed, but audit must not duplicate
        assert updated[0]["commercial_state"] == CommercialOpportunityState.CLOSED.value
        assert audit == []

    def test_identity_collision_44_vs_223_isolated(self) -> None:
        updated, _audit = compute_opportunity_lifecycle_updates(
            source_procurements=[
                {
                    "procurement_id": 301,
                    "source_table": "reestr_contract_44_fz",
                    "law_type": "44_FZ",
                    "contract_number": "CN-SAME",
                    "crm_stage": "torgi",
                    "award_status": "submission_open",
                },
                {
                    "procurement_id": 302,
                    "source_table": "reestr_contract_223_fz",
                    "law_type": "223_FZ",
                    "contract_number": "CN-SAME",
                    "crm_stage": "torgi",
                    "award_status": "submission_open",
                },
            ],
            opportunities=[
                {
                    "id": 3011,
                    "procurement_id": 301,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                },
                {
                    "id": 3022,
                    "procurement_id": 302,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                },
            ],
            existing_audit=[],
            now=_ts(),
        )

        by_id = {o["id"]: o for o in updated}
        assert by_id[3011]["commercial_state"] == CommercialOpportunityState.ACTIVE.value
        assert by_id[3022]["commercial_state"] == CommercialOpportunityState.ACTIVE.value

    def test_null_contract_number_identity_safe(self) -> None:
        updated, _audit = compute_opportunity_lifecycle_updates(
            source_procurements=[
                {
                    "procurement_id": 401,
                    "source_table": "reestr_contract_44_fz",
                    "source_id": 9001,
                    "law_type": "44_FZ",
                    "contract_number": None,
                    "crm_stage": "torgi",
                    "award_status": "submission_open",
                },
                {
                    "procurement_id": 402,
                    "source_table": "reestr_contract_44_fz",
                    "source_id": 9002,
                    "law_type": "44_FZ",
                    "contract_number": "   ",
                    "crm_stage": "torgi",
                    "award_status": "submission_open",
                },
            ],
            opportunities=[
                {
                    "id": 4011,
                    "procurement_id": 401,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                },
                {
                    "id": 4022,
                    "procurement_id": 402,
                    "commercial_category_code": "lighting",
                    "commercial_subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "commercial_state": "ACTIVE",
                    "last_source_event": "OPEN",
                    "source_sync_status": "OK",
                    "source_missing_since": None,
                },
            ],
            existing_audit=[],
            now=_ts(),
        )

        by_id = {o["id"]: o for o in updated}
        assert by_id[4011]["commercial_state"] == CommercialOpportunityState.ACTIVE.value
        assert by_id[4022]["commercial_state"] == CommercialOpportunityState.ACTIVE.value


def test_sync_wrapper_dry_run_no_writes() -> None:
    """Wrapper should not call execute_update when dry_run=True."""
    from unittest.mock import MagicMock

    crm_db = MagicMock()

    opp_rows = [
        {
            "id": 30,
            "procurement_id": 300,
            "commercial_category_code": "lighting",
            "commercial_subcategory_code": None,
            "opportunity_track": "DIRECT_SUPPLY",
            "commercial_state": "ACTIVE",
            "last_source_event": "OPEN",
            "source_sync_status": "OK",
            "source_missing_since": None,
        }
    ]
    src_rows = [
        {
            "procurement_id": 300,
            "source_table": "reestr_contract_44_fz_awarded",
            "contract_number": "CN-7",
            "crm_stage": "razygranye",
            "award_status": "awarded",
        }
    ]
    existing_audit: list[dict] = []

    crm_db.execute_query.side_effect = [opp_rows, src_rows, existing_audit]

    res = sync_opportunities_lifecycle(crm_db, dry_run=True, now=_ts(), limit=10)
    assert res["dry_run"] is True
    assert res["updated"] == 1
    assert res["transitions"] == 1
    crm_db.execute_update.assert_not_called()

