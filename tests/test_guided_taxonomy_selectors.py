from src.services.expert_annotation_service import load_subcategories_for_categories
from src.ui.components.analytics_v2.guided_annotation import (
    equivalent_known_value,
    normalize_taxonomy_text,
    sync_category_draft,
)
from src.ui.components.analytics_v2.annotation_card import _build_workbench_payload


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute_query(self, sql, params=None):
        self.calls.append((sql, params))
        return self.rows


def _model_row(code="WATERPROOFING"):
    return {
        "category_code": code,
        "subcategory_code": None,
        "opportunity_track": "EMBEDDED_MATERIAL",
        "model_opportunity_index": 0,
        "model_opportunity_snapshot": {"category_code": code},
    }


def test_active_selected_category_is_persisted_by_canonical_code_as_add():
    opportunities, rejected = [], []
    sync_category_draft(["FLOORING"], opportunities, rejected, [])
    assert opportunities[0]["category_code"] == "FLOORING"
    assert opportunities[0]["expert_action"] == "ADD"
    assert opportunities[0]["expert_reviewed"] is True


def test_explicit_model_category_acceptance_is_keep():
    opportunities, rejected = [], []
    sync_category_draft(["WATERPROOFING"], opportunities, rejected, [_model_row()])
    assert opportunities[0]["expert_action"] == "KEEP"
    assert opportunities[0]["model_opportunity_index"] == 0


def test_deselected_model_category_updates_shared_rejected_draft():
    opportunities, rejected = [], []
    sync_category_draft(["WATERPROOFING"], opportunities, rejected, [_model_row()])
    sync_category_draft([], opportunities, rejected, [_model_row()])
    assert opportunities == []
    assert rejected[0]["expert_action"] == "REJECT"
    assert rejected[0]["rejection_reason"] == "WRONG_CATEGORY"


def test_subcategories_are_batch_loaded_only_for_selected_categories():
    db = FakeDb([
        {"category_code": "A", "subcategory_code": "A1", "subcategory_name": "Alpha"},
        {"category_code": "B", "subcategory_code": "B1", "subcategory_name": "Beta"},
    ])
    result = load_subcategories_for_categories(["A", "B", "A"], db)
    assert set(result) == {"A", "B"}
    assert result["A"] == [{"code": "A1", "name": "Alpha"}]
    assert len(db.calls) == 1
    assert db.calls[0][1] == (["A", "B"],)


def test_no_selected_category_means_no_subcategory_sql():
    db = FakeDb([])
    assert load_subcategories_for_categories([], db) == {}
    assert db.calls == []


def test_new_value_normalization_avoids_case_and_whitespace_duplicates():
    known = ["Подземный паркинг"]
    assert normalize_taxonomy_text("  Подземный   паркинг ") == "Подземный паркинг"
    assert equivalent_known_value("ПОДЗЕМНЫЙ   ПАРКИНГ ", known) == "Подземный паркинг"


def test_model_raw_is_not_a_vocabulary_source_by_construction():
    # The selector utilities accept an explicit human-known list; no assessment/model argument exists.
    assert equivalent_known_value("Model-only value", ["Экспертное значение"]) is None


def test_known_value_positive_payload_requires_no_taxonomy_free_text(monkeypatch):
    import src.ui.components.analytics_v2.annotation_card as card

    opportunity = {
        "expert_rank": 1,
        "expert_action": "ADD",
        "category_code": "lighting",
        "subcategory_code": "road_lighting",
        "opportunity_track": "EMBEDDED_MATERIAL",
        "model_opportunity_index": None,
        "expert_reviewed": True,
    }
    monkeypatch.setattr(card.st, "session_state", {
        "ann_77_opps": [opportunity],
        "ann_77_rejected": [],
        "ann_77_obj_type": "Транспортная инфраструктура",
        "ann_77_obj_subtype": "Автомобильная дорога",
        "ann_77_work_stage": "Строительно-монтажные работы",
        "ann_77_medal": "SILVER",
        "ann_77_completeness": "COMPLETE",
        "ann_77_review_scope": "FULL",
        "ann_77_evidence_state": "SUFFICIENT",
        "ann_77_absence_confirmed": False,
        "ann_77_document_priorities": {},
        "ann_77_proposals": [],
        "ann_77_obj_type_known_values": ["Транспортная инфраструктура"],
        "ann_77_obj_subtype_known_values": ["Автомобильная дорога"],
        "ann_77_work_stage_known_values": ["Строительно-монтажные работы"],
    })
    payload = _build_workbench_payload(77, None, "expert")
    assert payload["opportunities"][0]["category_code"] == "lighting"
    assert payload["opportunities"][0]["subcategory_code"] == "road_lighting"
    assert payload["expert_object_type"] == "Транспортная инфраструктура"
    assert payload["expert_work_stage"] == "Строительно-монтажные работы"
    assert payload["expert_medal"] == "SILVER"
    assert payload["taxonomy_proposals"] == []
