"""Phase B — expert annotation workbench tests."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from src.services.annotation_queue_service import (
    ANNOTATION_FILTER_ANNOTATED,
    ANNOTATION_FILTER_UNANNOTATED,
    AnnotationQueueFilters,
    MODEL_SOURCE_LEGACY,
    MODEL_SOURCE_RAW,
    PUBLICATION_FILTER_ALL,
    QUEUE_MODE_ALL_CURRENT,
    QUEUE_MODE_OPEN_ASSESSED,
    batch_publication_visibility,
    build_queue_where,
    fetch_queue_counters,
    fetch_queue_ids,
    lifecycle_label,
    queue_order_sql,
)
from src.services.torgi_publication import torgi_publication_sql_filters
from src.ui.components.analytics_v2.annotation_card import (
    _build_out_of_profile_payload,
    _training_evidence_quality,
    model_category_rows,
    rejected_raw_categories,
)
from src.ui.components.analytics_v2.annotation_queue import bind_and_advance, GO_NEXT_KEY, GO_NEXT_FROM_KEY


class _FakeDb:
    def __init__(self, responses: list | None = None, *, has_inference: bool = False) -> None:
        self.responses = list(responses or [])
        self.queries: list[tuple[str, tuple | None]] = []
        self.has_inference = has_inference

    def execute_scalar(self, sql):
        if "crm_v3_model_inference_runs" in sql:
            return self.has_inference
        return True

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        if "information_schema.columns" in sql:
            return [{"?column?": 1}] if self.has_inference else []
        if not self.responses:
            return []
        item = self.responses.pop(0)
        return item if isinstance(item, list) else [item]


def test_build_queue_where_open_assessed_default() -> None:
    sql, params = build_queue_where(AnnotationQueueFilters())
    assert "crm_stage = 'torgi'" in sql
    assert "is_current = TRUE" in sql
    assert "NOT EXISTS" in sql  # unannotated
    assert params == []


def test_build_queue_where_with_shadow_when_schema_ready() -> None:
    sql, _ = build_queue_where(
        AnnotationQueueFilters(),
        has_inference_run_id=True,
        has_inference_runs_table=True,
    )
    assert "run_kind = 'SHADOW'" in sql


def test_build_queue_where_all_current_assessments() -> None:
    sql, _ = build_queue_where(
        AnnotationQueueFilters(
            queue_mode=QUEUE_MODE_ALL_CURRENT,
            annotation_status=ANNOTATION_FILTER_ANNOTATED,
        )
    )
    assert "crm_stage = 'torgi'" not in sql
    assert "crm_v3_expert_annotations ea" in sql


def test_build_queue_where_model_source_filters() -> None:
    raw_sql, _ = build_queue_where(
        AnnotationQueueFilters(model_source=MODEL_SOURCE_RAW)
    )
    assert "inference_run_id IS NOT NULL" in raw_sql
    leg_sql, _ = build_queue_where(
        AnnotationQueueFilters(model_source=MODEL_SOURCE_LEGACY)
    )
    assert "inference_run_id IS NULL" in leg_sql


def test_queue_order_is_deterministic() -> None:
    assert "end_date ASC" in queue_order_sql(
        AnnotationQueueFilters(queue_mode=QUEUE_MODE_OPEN_ASSESSED)
    )
    assert queue_order_sql(
        AnnotationQueueFilters(queue_mode=QUEUE_MODE_ALL_CURRENT)
    ) == "ai.id ASC, cp.id ASC"


def test_fetch_queue_ids_bypasses_publication_sql() -> None:
    db = _FakeDb([[{"id": 1}, {"id": 2}]])
    ids = fetch_queue_ids(db, AnnotationQueueFilters(publication_visibility=PUBLICATION_FILTER_ALL))
    assert len(ids) == 2
    sql = db.queries[0][0]
    assert "commercial_state IN" not in sql


def test_fetch_queue_counters_shape() -> None:
    db = _FakeDb([[
        {
            "canonical_open": 3025,
            "open_assessed": 66,
            "open_without_assessment": 2959,
            "all_current_assessments": 3693,
            "publication_visible_open_assessed": 20,
            "publication_hidden_open_assessed": 46,
            "expert_annotations_total": 5,
        }
    ]])
    c = fetch_queue_counters(db)
    assert c["open_assessed"] == 66
    assert c["all_current_assessments"] == 3693


def test_lifecycle_label_open() -> None:
    row = {
        "crm_stage": "torgi",
        "award_status": "submission_open",
        "end_date": date.today() + timedelta(days=3),
    }
    assert lifecycle_label(row) == "OPEN"


def test_model_category_rows_legacy_not_validated() -> None:
    rows = model_category_rows({
        "model_provenance": "UNKNOWN_LEGACY",
        "normalized_result": {
            "category_opportunities": [{"category_code": "C01"}],
        },
    })
    assert rows[0]["provenance"] == "LEGACY_BUSINESS"


def test_model_category_rows_validated() -> None:
    rows = model_category_rows({
        "model_provenance": "MODEL_VALIDATED",
        "inference_run_id": 9,
        "validated_model_result": {
            "commercial_category_hypotheses": [
                {"category_code": "paint", "confidence": 0.8},
            ],
        },
    })
    assert rows[0]["category_code"] == "paint"
    assert rows[0]["provenance"] == "MODEL_VALIDATED"


def test_rejected_raw_categories_renderable() -> None:
    rejected = rejected_raw_categories({
        "model_provenance": "MODEL_VALIDATED",
        "validation_status": "INVALID",
        "validation_errors": ["UNKNOWN_CATEGORY_CODE:computer_components"],
        "validated_model_result": {"commercial_category_hypotheses": []},
        "raw_model_json": {
            "commercial_category_hypotheses": [
                {"category_code": "computer_components"},
            ],
        },
    })
    assert rejected[0]["raw_category_code"] == "computer_components"
    assert "UNKNOWN_CATEGORY_CODE" in rejected[0]["validation_errors"][0]


def test_training_evidence_quality_markers() -> None:
    assert _training_evidence_quality({"model_provenance": "UNKNOWN_LEGACY"}) == "LEGACY_NO_RAW"
    assert _training_evidence_quality({
        "model_provenance": "MODEL_VALIDATED",
        "inference_run_id": 1,
    }) == "IMMUTABLE_MODEL_TRACE"


def test_out_of_profile_payload() -> None:
    payload = _build_out_of_profile_payload(
        {
            "id": 3,
            "model_provenance": "UNKNOWN_LEGACY",
            "normalized_result": {
                "category_opportunities": [{"category_code": "noise"}],
            },
        },
        "tester",
    )
    assert payload["expert_scope_verdict"] == "OUT_OF_PROFILE"
    assert payload["rejected_model_opportunities"][0]["rejection_reason"] == "OUT_OF_PROFILE"
    assert payload["training_evidence_quality"] == "LEGACY_NO_RAW"


def test_save_next_advances_full_queue() -> None:
    queue = [10, 20, 30, 40]
    session_key = "annotation_wb_queue"
    session = {session_key: 10, GO_NEXT_KEY: True, GO_NEXT_FROM_KEY: 10}
    cards = bind_and_advance(
        [{"id": i} for i in queue],
        session_key,
        session,
    )
    assert cards[0]["id"] == 20
    assert session[session_key] == 20


def test_publication_visibility_batch_mock(monkeypatch) -> None:
    today = date.today()
    monkeypatch.setattr(
        "src.services.annotation_queue_service.publication_schema_ready",
        lambda _db: True,
    )

    class PubDb:
        def execute_query(self, sql, params=None):
            if "crm_procurements" in sql and "end_date" in sql:
                return [{
                    "id": params[0],
                    "crm_stage": "torgi",
                    "award_status": "submission_open",
                    "end_date": today + timedelta(days=1),
                }]
            if "procurement_ai_assessments" in sql:
                return [{
                    "procurement_id": params[0],
                    "status": "SUCCESS",
                    "normalized_result": {
                        "business_scope_status": "IN_PROFILE",
                        "category_opportunities": [],
                    },
                }]
            return [{
                "procurement_id": params[0],
                "category_code": "C01",
                "commercial_state": "ACTIVE",
                "status": "CURRENT",
            }]

    vis = batch_publication_visibility(PubDb(), [99])
    assert vis[99] is True


def test_torgi_publication_sql_unchanged_in_tabs() -> None:
    from pathlib import Path

    tabs = Path("src/ui/components/analytics_v2/tabs.py").read_text(encoding="utf-8")
    assert "torgi_publication_sql_filters" in tabs
    assert "expert_annotation" not in tabs
