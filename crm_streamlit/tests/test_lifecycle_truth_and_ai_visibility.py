"""Regression tests for effective lifecycle truth + AI decision visibility."""
from __future__ import annotations

from datetime import date, timedelta

from src.services.ai_decision_summary import UNDEFINED, build_ai_decision_summary
from src.services.commercial_routing_v3.projection import (
    SourceStage,
    resolve_lifecycle_identity,
    stage_from_source_table,
)
from src.services.commercial_routing_v3.source_lifecycle import (
    SourceLifecycleEvent,
    lifecycle_crm_stage_status,
    normalize_source_lifecycle_event,
)
from src.services.effective_lifecycle import (
    LAW_44,
    LAW_223,
    LAW_615,
    LAW_615_IN_ANALYTICS_WORKSET,
    factual_awarded_sql,
    factual_commission_sql,
    factual_open_torgi_sql,
    law_filter_sql,
    open_row_award_status,
)
from src.services.source_contour import LAW_44 as SC44


def test_null_deadline_not_open():
    event = normalize_source_lifecycle_event(
        source_table="reestr_contract_44_fz",
        crm_stage="torgi",
        award_status="submission_open",
        end_date=None,
    )
    assert event == SourceLifecycleEvent.UNKNOWN
    stage, status = lifecycle_crm_stage_status(event, source_table="reestr_contract_44_fz")
    assert status != "submission_open"
    assert open_row_award_status(None) != "submission_open"


def test_past_deadline_not_torgi_open():
    event = normalize_source_lifecycle_event(
        source_table="reestr_contract_44_fz",
        end_date=date.today() - timedelta(days=1),
    )
    assert event == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
    assert open_row_award_status(date.today() - timedelta(days=2)) == "submission_closed_waiting_award"


def test_future_deadline_is_open():
    event = normalize_source_lifecycle_event(
        source_table="reestr_contract_223_fz",
        end_date=date.today() + timedelta(days=10),
    )
    assert event == SourceLifecycleEvent.OPEN
    assert open_row_award_status(date.today() + timedelta(days=10)) == "submission_open"


def test_awarded_table_outranks_open():
    assert stage_from_source_table("reestr_contract_44_fz_awarded") == SourceStage.AWARDED
    assert stage_from_source_table("reestr_contract_44_fz") == SourceStage.OPEN
    assert stage_from_source_table("reestr_contract_44_fz_commission_work") == SourceStage.WAITING_SOURCE_OUTCOME


def test_canonical_identity_by_law_and_number():
    a = resolve_lifecycle_identity(
        source_table="reestr_contract_44_fz",
        source_id=1,
        contract_number="32515489436",
    )
    b = resolve_lifecycle_identity(
        source_table="reestr_contract_44_fz_awarded",
        source_id=99,
        contract_number="32515489436",
    )
    assert a.contract_number == b.contract_number == "32515489436"
    assert a.key()[0] == "stable"
    assert a.key()[1] == b.key()[1]


def test_torgi_sql_requires_deadline_and_excludes_superseded():
    sql = factual_open_torgi_sql("cp")
    assert "end_date IS NOT NULL" in sql
    assert "submission_open" in sql
    assert "razygranye" in sql
    assert "CURRENT_DATE" in sql


def test_commission_sql_requires_known_past_deadline():
    sql = factual_commission_sql("cp")
    assert "end_date IS NOT NULL" in sql
    assert "end_date < CURRENT_DATE" in sql
    assert "award_not_found" in sql


def test_law_filters():
    assert "44" in law_filter_sql("cp", LAW_44)
    assert "223" in law_filter_sql("cp", LAW_223)
    assert "615" in law_filter_sql("cp", LAW_615)
    assert law_filter_sql("cp", "ALL") == "TRUE"
    assert LAW_615_IN_ANALYTICS_WORKSET is False
    assert "razygranye" in factual_awarded_sql("cp", law=LAW_44)


def test_ai_summary_undefined_when_missing():
    summary = build_ai_decision_summary(None)
    assert summary["read_only"] is True
    assert all(value == UNDEFINED for _, value in summary["fields"])
    labels = [label for label, _ in summary["fields"]]
    assert "Объект" in labels
    assert "Категория" in labels
    assert "Medal" in labels


def test_ai_summary_uses_validated_model_fields():
    assessment = {
        "inference_run_id": "run-1",
        "validated_model_result": {
            "object_classification": {
                "object_type": "KINDERGARTEN",
                "object_subtype": None,
                "work_stage": "WORKS",
            },
            "procurement_form": "WORKS",
            "commercial_category_hypotheses": [
                {
                    "category_code": "waterproofing",
                    "subcategory_code": "membranes",
                    "confidence": 0.8,
                }
            ],
        },
    }
    summary = build_ai_decision_summary(assessment)
    values = dict(summary["fields"])
    assert values["Объект"] == "KINDERGARTEN"
    assert values["Категория"] == "waterproofing"
    assert values["Подкатегория"] == "membranes"
    assert values["Режим закупки"] == "WORKS"


def test_tabs_wire_law_filter_and_factual_sql():
    from pathlib import Path

    tabs = Path("src/ui/components/analytics_v2/tabs.py").read_text(encoding="utf-8")
    assert "_render_law_filter" in tabs
    assert "factual_open_torgi_sql" in tabs
    assert "factual_commission_sql" in tabs
    ws = Path("src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
    assert "_render_ai_decision_block" in ws
    assert "ИИ предложил" in ws
