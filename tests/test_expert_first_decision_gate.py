from pathlib import Path

from src.services.annotation_state_service import NOT_INTERESTING, classify_annotation_payload
from src.ui.components.analytics_v2.annotation_card import (
    REJECTION_REASONS,
    SCOPE_DECISIONS,
    _build_out_of_profile_payload,
)
from src.ui.components.analytics_v2.stage_workspace import format_okpd_preview


def test_okpd_preview_code_and_name_are_factual():
    assert format_okpd_preview({"okpd_code": "32.50.13", "okpd_name": "Изделия медицинские"}) == (
        "32.50.13 — Изделия медицинские"
    )


def test_okpd_preview_code_only():
    assert format_okpd_preview({"okpd_code": "32.50.13"}) == "32.50.13"


def test_okpd_preview_absent_omits_row():
    assert format_okpd_preview({"okpd_code": None, "okpd_name": "—"}) is None


def test_primary_question_precedes_advanced_navigation_and_uses_three_values():
    source = Path("src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
    assert SCOPE_DECISIONS == ("YES", "NO", "UNCERTAIN")
    render_loop = source.split("for card in visible:", 1)[1].split("return \"INLINE\"", 1)[0]
    assert render_loop.index("_render_first_decision_gate") < render_loop.index("Раздел карточки")
    assert all(label in source for label in ("✓ Да", "✕ Нет", "? Не уверен"))


def test_no_builds_existing_canonical_out_of_profile_contract_without_advanced_fields():
    assessment = {
        "id": 91,
        "model_provenance": "MODEL_VALIDATED",
        "inference_run_id": "immutable-run",
        "validated_model_result": {
            "commercial_category_hypotheses": [
                {"category_code": "medical", "subcategory_code": "gloves"}
            ]
        },
    }
    payload = _build_out_of_profile_payload(assessment, "expert")
    assert payload["expert_scope_verdict"] == "OUT_OF_PROFILE"
    assert payload["expert_commercial_verdict"] == "NO_COMMERCIAL_ENTRY"
    assert payload["expert_medal"] == "NCE"
    assert payload["annotation_review_scope"] == "OUT_OF_PROFILE"
    assert payload["annotation_completeness"] == "COMPLETE"
    assert payload["opportunities"] == []
    assert payload["expert_object_type"] is None
    assert payload["expert_object_subtype"] is None
    assert payload["expert_work_stage"] is None
    assert classify_annotation_payload(payload) == NOT_INTERESTING
    assert payload["model_assessment_id"] == 91


def test_rejection_reason_is_optional_additive_json_metadata_without_schema_change():
    assert set(REJECTION_REASONS) == {
        "NOT_OUR_PRODUCT_OR_WORK", "NOT_OUR_OBJECT", "NOT_OUR_STAGE", "OTHER"
    }
    payload = _build_out_of_profile_payload(None, "expert")
    assert "expert_out_of_profile_reason" not in payload
    assert payload["model_assessment_id"] is None


def test_human_labels_replace_raw_primary_widget_labels():
    source = Path("src/ui/components/analytics_v2/annotation_card.py").read_text(encoding="utf-8")
    assert 'st.text_input("expert_object_type"' not in source
    assert 'st.text_input("expert_object_subtype"' not in source
    assert 'st.text_input("expert_work_stage"' not in source
    assert 'st.selectbox("annotation_review_scope"' not in source
    for label in ("Тип объекта", "Подтип / уточнение объекта", "Стадия / вид работ", "Объём проверки"):
        assert label in source


def test_model_input_and_queue_are_outside_this_ui_wip():
    source = Path("src/ui/components/analytics_v2/annotation_card.py").read_text(encoding="utf-8")
    assert "ensure_v3_model_input" not in source
    assert "crm_v3_inference_jobs" not in source
