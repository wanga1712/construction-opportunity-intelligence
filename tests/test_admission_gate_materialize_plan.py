"""Targeted dry-run planning tests for admission materialisation."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "admission_gate_materialize",
    ROOT / "scripts" / "admission_gate_materialize.py",
)
assert SPEC and SPEC.loader
materialize = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = materialize
SPEC.loader.exec_module(materialize)


def _procurement(**extra):
    return {
        "id": 1,
        "source_table": "reestr_contract_44_fz",
        "crm_stage": "torgi",
        "award_status": "submission_open",
        "end_date": "2099-12-31",
        "auction_name": "Поставка строительных материалов",
        "okpd_code": "23.32.11",
        **extra,
    }


def test_default_is_dry_run() -> None:
    args = materialize.build_parser().parse_args([])
    assert args.apply is False
    apply_args = materialize.build_parser().parse_args(["--apply"])
    assert apply_args.apply is True


def test_plan_returns_required_dry_run_sections() -> None:
    plan = materialize.plan_from_records(
        [1],
        {1: _procurement()},
        {},
        [{"id": 10, "procurement_id": 1, "category_context": {}}],
        evaluated_at="2026-11-09T00:00:00+00:00",
    )
    output = plan.as_dict()
    assert output["inspected"] == 1
    assert output["planned_admission_changes"]["count"] == 1
    assert output["planned_crm_writes"] == {
        "count": 1,
        "by_operation": {"insert": 1},
    }
    assert output["planned_queue_changes"]["count"] == 1
    assert output["skipped"] == {}
    assert output["errors"] == []


def test_authority_only_never_plans_queue_changes() -> None:
    plan = materialize.plan_from_records(
        [1],
        {1: _procurement()},
        {},
        [{"id": 10, "procurement_id": 1, "category_context": {}}],
        authority_only=True,
    )
    output = plan.as_dict()
    assert output["planned_queue_changes"]["count"] == 0
    assert output["skipped"]["queue_reconciliation_skipped"] == 1


def test_missing_crm_procurement_is_reported_as_skipped() -> None:
    plan = materialize.plan_from_records([99], {}, {}, [])
    output = plan.as_dict()
    assert output["inspected"] == 1
    assert output["planned_crm_writes"]["count"] == 0
    assert output["skipped"]["missing_crm_procurement"] == 1
