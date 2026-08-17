"""Unit tests: WAITING execution eligibility + FAILED backoff."""
from datetime import datetime, timedelta, timezone

from src.services.commercial_routing_v3.routing_eligibility import evaluate_routing_eligibility
from src.services.commercial_routing_v3.routing_runtime_config import failed_retry_backoff_sec


def _base_proc(**kwargs):
    now = datetime.now(timezone.utc)
    proc = {
        "source_table": "reestr_contract_44_fz",
        "source_id": 12345,
        "contract_number": "0000000000000000001",
        "crm_stage": "torgi",
        "award_status": "accepting_applications",
        "end_date": now.date() + timedelta(days=10),
        "okpd_code": "41.20.10.000",
        "auction_name": "Строительство школы №1 капитальный ремонт",
        "ai_assessment_status": "UNASSESSED",
        "ai_routing_attempt_count": 0,
    }
    proc.update(kwargs)
    return proc


def test_failed_retry_backoff_grows_and_caps():
    assert failed_retry_backoff_sec(1) == 300
    assert failed_retry_backoff_sec(2) == 600
    assert failed_retry_backoff_sec(5) == 3600


def test_waiting_not_selectable_when_flag_off(monkeypatch):
    monkeypatch.setenv("CRM_V3_WAITING_ROUTABLE", "0")
    import importlib
    import src.services.commercial_routing_v3.routing_runtime_config as cfg
    import src.services.commercial_routing_v3.routing_eligibility as elig

    importlib.reload(cfg)
    importlib.reload(elig)
    proc = _base_proc(
        award_status="submission_closed_waiting_award",
        end_date=datetime.now(timezone.utc).date() - timedelta(days=1),
    )
    d = elig.evaluate_routing_eligibility(proc, priors=[])
    assert d.selectable is False
    assert d.reason == "WAITING_NOT_ROUTABLE"


def test_failed_backoff_blocks_immediate_retry():
    now = datetime.now(timezone.utc)
    proc = _base_proc(
        ai_assessment_status="FAILED",
        ai_routing_attempt_count=1,
        ai_routing_error_class="UNEXPECTED_EXCEPTION",
        ai_assessed_at=now - timedelta(seconds=30),
    )
    d = evaluate_routing_eligibility(proc, priors=[], now=now)
    assert d.selectable is False
    assert d.reason == "FAILED_BACKOFF"
