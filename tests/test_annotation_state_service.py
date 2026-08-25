from src.services.annotation_state_service import (
    ANNOTATED, NOT_INTERESTING, REVIEWED, UNANNOTATED, UNREVIEWED,
    annotation_state_counts,
    classify_annotation_payload, load_current_annotation_states,
)

def test_payload_states_are_mutually_exclusive():
    assert classify_annotation_payload(None) == UNANNOTATED
    assert classify_annotation_payload({"annotation_completeness": "COMPLETE"}) == ANNOTATED
    assert classify_annotation_payload({"annotation_completeness": "PARTIAL"}) == ANNOTATED
    assert classify_annotation_payload({"expert_scope_verdict": "OUT_OF_PROFILE"}) == NOT_INTERESTING
    assert classify_annotation_payload({"expert_medal": "NCE"}) == NOT_INTERESTING
    assert classify_annotation_payload({"error_reasons": ["OUT_OF_PROFILE"]}) == NOT_INTERESTING

class DB:
    def __init__(self): self.calls = []
    def execute_query(self, sql, params):
        self.calls.append((sql, params))
        return [{"id": 7, "procurement_id": 2, "annotation_version": 1,
                 "created_at": "now", "payload": {"annotation_completeness": "PARTIAL"}},
                {"id": 8, "procurement_id": 3, "annotation_version": 1,
                 "created_at": "now", "payload": {"expert_medal": "NCE"}}]

def test_batch_loader_one_query_and_review_progress_with_outcome_subset():
    db = DB(); states = load_current_annotation_states([1, 2, 3], db)
    assert len(db.calls) == 1
    assert [states[i]["annotation_state"] for i in (1, 2, 3)] == [UNANNOTATED, ANNOTATED, NOT_INTERESTING]
    counts = annotation_state_counts(states)
    assert counts["ALL"] == counts[UNREVIEWED] + counts[REVIEWED] == 3
    assert counts[REVIEWED] == 2
    assert counts[NOT_INTERESTING] == 1
    assert counts[NOT_INTERESTING] <= counts[REVIEWED]
