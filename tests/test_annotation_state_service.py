from src.services.annotation_category_gate import CATEGORY_SCOPE_FIELD, OUT_OF_CATEGORY
from src.services.annotation_state_service import (
    ANNOTATED,
    LEGACY_NOT_INTERESTING,
    NOT_INTERESTING,
    REVIEWED,
    UNANNOTATED,
    UNREVIEWED,
    annotation_state_counts,
    classify_annotation_payload,
    load_current_annotation_states,
)


def test_payload_states_are_mutually_exclusive():
    assert classify_annotation_payload(None) == UNANNOTATED
    assert classify_annotation_payload({"annotation_completeness": "COMPLETE"}) == ANNOTATED
    assert classify_annotation_payload({"annotation_completeness": "PARTIAL"}) == ANNOTATED
    assert classify_annotation_payload({"expert_scope_verdict": "OUT_OF_PROFILE"}) == NOT_INTERESTING
    assert classify_annotation_payload({"expert_medal": "NCE"}) == NOT_INTERESTING
    assert classify_annotation_payload({"error_reasons": ["OUT_OF_PROFILE"]}) == NOT_INTERESTING
    assert classify_annotation_payload({CATEGORY_SCOPE_FIELD: OUT_OF_CATEGORY}) == OUT_OF_CATEGORY


class DB:
    def __init__(self):
        self.calls = []

    def execute_query(self, sql, params):
        self.calls.append((sql, params))
        return [
            {
                "id": 7,
                "procurement_id": 2,
                "annotation_version": 1,
                "created_at": "now",
                "payload": {"annotation_completeness": "PARTIAL"},
            },
            {
                "id": 8,
                "procurement_id": 3,
                "annotation_version": 1,
                "created_at": "now",
                "payload": {"expert_medal": "NCE"},
            },
        ]


def test_batch_loader_one_query_and_partition():
    db = DB()
    states = load_current_annotation_states([1, 2, 3], db)
    assert len(db.calls) == 1
    assert states[1]["is_category_reviewed"] is False
    assert states[2]["is_category_reviewed"] is False
    assert states[3]["is_legacy_negative"] is True
    counts = annotation_state_counts(states)
    assert counts["ALL"] == counts[UNREVIEWED] + counts[REVIEWED] == 3
    assert counts[LEGACY_NOT_INTERESTING] == 1
    assert counts[UNANNOTATED] == counts[UNREVIEWED]
