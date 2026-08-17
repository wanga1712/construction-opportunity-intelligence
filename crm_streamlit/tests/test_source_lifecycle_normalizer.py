"""Canonical source lifecycle normalizer tests (incl. temporal deadline)."""
from __future__ import annotations

from datetime import date, timedelta

from src.domain.commercial_opportunity_lifecycle import SourceLifecycleEvent
from src.services.commercial_routing_v3.source_lifecycle import (
    lifecycle_crm_stage_status,
    normalize_source_lifecycle_event,
)


def test_forward_active_deadline_maps_open() -> None:
    assert (
        normalize_source_lifecycle_event(
            source_table="reestr_contract_44_fz",
            crm_stage="torgi",
            award_status="submission_open",
            end_date=date.today() + timedelta(days=3),
        )
        == SourceLifecycleEvent.OPEN
    )


def test_open_table_past_deadline_maps_waiting() -> None:
    assert (
        normalize_source_lifecycle_event(
            source_table="reestr_contract_44_fz",
            crm_stage="torgi",
            award_status="submission_open",
            end_date=date.today() - timedelta(days=1),
        )
        == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
    )


def test_backward_past_deadline_not_active_open() -> None:
    """Backward may insert into open table today with already-past end_date."""
    ev = normalize_source_lifecycle_event(
        source_table="reestr_contract_223_fz",
        crm_stage="torgi",
        award_status="submission_closed_waiting_award",
        end_date=date.today() - timedelta(days=10),
    )
    assert ev == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
    stage, status = lifecycle_crm_stage_status(ev, source_table="reestr_contract_223_fz")
    assert stage == "torgi"
    assert status == "submission_closed_waiting_award"


def test_commission_maps_waiting() -> None:
    assert (
        normalize_source_lifecycle_event(
            source_table="reestr_contract_44_fz_commission_work",
            crm_stage="commission",
            award_status="commission",
        )
        == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
    )


def test_award_not_found_maps_waiting() -> None:
    assert (
        normalize_source_lifecycle_event(
            source_table="reestr_contract_44_fz",
            crm_stage="torgi",
            award_status="award_not_found",
            end_date=date.today() + timedelta(days=5),
        )
        == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
    )


def test_awarded_maps_awarded() -> None:
    assert (
        normalize_source_lifecycle_event(
            source_table="reestr_contract_44_fz_awarded",
            crm_stage="razygranye",
            award_status="awarded",
            end_date=date.today() - timedelta(days=30),
        )
        == SourceLifecycleEvent.AWARDED
    )


def test_null_deadline_on_open_stays_open() -> None:
    assert (
        normalize_source_lifecycle_event(
            source_table="reestr_contract_44_fz",
            crm_stage="torgi",
            award_status="submission_open",
            end_date=None,
        )
        == SourceLifecycleEvent.OPEN
    )
