"""Tests for staged object + procurement-mode annotation + fast category triage."""
from __future__ import annotations

from src.services.annotation_category_gate import (
    CATEGORY_SCOPE_FIELD,
    IN_CATEGORY,
    OUT_OF_CATEGORY,
    UNCERTAIN,
    build_in_category_payload,
    build_out_of_category_payload,
    build_uncertain_payload,
)
from src.services.annotation_staged import (
    is_category_triage_complete,
    is_deep_annotation_complete,
    is_partially_reviewed,
    is_staged_complete,
    merge_staged_fields,
    staged_card_summary,
)
from src.services.annotation_state_service import (
    REVIEWED,
    UNREVIEWED,
    annotation_state_counts,
    load_current_annotation_states,
)
from src.services.expert_object_taxonomy import (
    OBJECT_SECTOR_FIELD,
    OBJECT_TYPE_FIELD,
    taxonomy_stats,
)
from src.services.expert_procurement_mode import (
    DIRECT_SUPPLY,
    PROCUREMENT_MODE_FIELD,
    PROJECT,
    PROJECT_AND_WORKS,
    UNCERTAIN as MODE_UNCERTAIN,
    WORKS,
)
from src.services.source_contour import LAW_44, LAW_223, LAW_615, resolve_source_contour
from src.ui.components.analytics_v2.stage_workspace import FILTERS
from src.ui.components.analytics_v2.staged_annotation_ui import validate_staged_minimum


def test_source_contour_is_factual_read_only_authority():
    c223 = resolve_source_contour("procurements_223")
    assert c223["law_code"] == LAW_223
    assert "Корпоративная" in c223["contour_label"]
    assert c223["law_label"] == "223-ФЗ"

    c44 = resolve_source_contour("notice_44fz")
    assert c44["law_code"] == LAW_44
    assert "Государственная" in c44["contour_label"]

    c615 = resolve_source_contour("torgi_615_pp")
    assert c615["law_code"] == LAW_615
    assert "Капитальный ремонт" in c615["contour_label"]

    assert resolve_source_contour("notice_44_commercial_looking")["law_code"] == LAW_44


def test_object_controlled_taxonomy_exists():
    stats = taxonomy_stats()
    assert stats["sectors"] >= 6
    assert stats["types"] >= 10


def test_procurement_modes_persist_in_payload():
    for mode in (PROJECT, WORKS, PROJECT_AND_WORKS, DIRECT_SUPPLY, MODE_UNCERTAIN):
        base = build_out_of_category_payload(assessment=None, created_by="t")
        payload = merge_staged_fields(
            base,
            object_sector="RESIDENTIAL",
            object_type="APARTMENT_BUILDING",
            procurement_mode=mode,
        )
        assert payload[PROCUREMENT_MODE_FIELD] == mode
        assert payload[OBJECT_SECTOR_FIELD] == "RESIDENTIAL"
        assert payload[OBJECT_TYPE_FIELD] == "APARTMENT_BUILDING"
        assert is_staged_complete(payload)
        assert is_category_triage_complete(payload)


def test_category_gate_preserved_with_staged_fields():
    from src.services.expert_commercial_entry import COMMERCIAL
    from src.services.expert_medal_stage import GOLD

    base = build_in_category_payload(
        assessment={"id": 1},
        created_by="t",
        category_codes=["waterproofing"],
        category_names={"waterproofing": "Гидроизоляция"},
    )
    payload = merge_staged_fields(
        base,
        object_sector="RESIDENTIAL",
        object_type="APARTMENT_BUILDING",
        procurement_mode=WORKS,
        commercial_entry=COMMERCIAL,
        expert_medal=GOLD,
    )
    assert payload[CATEGORY_SCOPE_FIELD] == IN_CATEGORY
    assert payload["expert_category_codes"] == ["waterproofing"]
    assert is_staged_complete(payload)
    assert is_deep_annotation_complete(payload)


def test_out_of_category_sparse_row_is_valid_without_object_or_mode():
    payload = build_out_of_category_payload(assessment=None, created_by="t")
    assert payload[CATEGORY_SCOPE_FIELD] == OUT_OF_CATEGORY
    assert payload["expert_category_codes"] == []
    assert is_category_triage_complete(payload)
    assert is_staged_complete(payload)
    assert not is_deep_annotation_complete(payload)
    assert not is_partially_reviewed(payload)
    summary = staged_card_summary(payload)
    assert summary["status"] == "TRIAGED"
    assert summary["lines"] == [("⛔", "Вне товарных категорий")]
    assert validate_staged_minimum({}, require_in_category_extras=False) == []


def test_out_of_category_with_optional_deep_fields_still_complete():
    payload = merge_staged_fields(
        build_out_of_category_payload(assessment=None, created_by="t"),
        object_sector="INFRASTRUCTURE",
        object_type="ENERGY_INFRASTRUCTURE",
        procurement_mode=DIRECT_SUPPLY,
    )
    assert is_staged_complete(payload)
    # Compact card must not clutter with object/mode for OUT.
    summary = staged_card_summary(payload)
    assert summary["lines"] == [("⛔", "Вне товарных категорий")]


def test_uncertain_fast_defer_without_deep_fields():
    payload = build_uncertain_payload(assessment=None, created_by="t")
    assert payload[CATEGORY_SCOPE_FIELD] == UNCERTAIN
    assert is_category_triage_complete(payload)
    assert is_staged_complete(payload)
    assert not is_deep_annotation_complete(payload)
    summary = staged_card_summary(payload)
    assert summary["status"] == "TRIAGED"


def test_legacy_category_only_out_is_triaged_not_partial():
    payload = {CATEGORY_SCOPE_FIELD: OUT_OF_CATEGORY}
    assert is_category_triage_complete(payload)
    assert is_staged_complete(payload)
    assert not is_partially_reviewed(payload)

    class DB:
        def execute_query(self, sql, params):
            return [
                {
                    "id": 1,
                    "procurement_id": 10,
                    "annotation_version": 1,
                    "created_at": "t",
                    "payload": payload,
                },
                {
                    "id": 2,
                    "procurement_id": 11,
                    "annotation_version": 1,
                    "created_at": "t",
                    "payload": merge_staged_fields(
                        build_out_of_category_payload(assessment=None, created_by="t"),
                        object_sector="SOCIAL",
                        object_type="SCHOOL",
                        procurement_mode=WORKS,
                    ),
                },
            ]

    states = load_current_annotation_states([10, 11, 12], DB())
    counts = annotation_state_counts(states)
    assert counts["ALL"] == counts[UNREVIEWED] + counts[REVIEWED] == 3
    assert counts[REVIEWED] == 2
    assert counts[UNREVIEWED] == 1
    assert counts[OUT_OF_CATEGORY] == 2
    assert counts["CATEGORY_TRIAGE_REVIEWED"] == 2
    assert counts["DEEP_ANNOTATION_COMPLETE"] == 0
    assert states[10]["is_category_reviewed"] is True
    assert states[10]["is_staged_complete"] is True
    assert states[11]["is_staged_complete"] is True


def test_in_category_partial_until_deep_complete():
    base = build_in_category_payload(
        assessment=None, created_by="t", category_codes=["waterproofing"]
    )
    assert is_category_triage_complete(base)
    assert not is_staged_complete(base)
    assert is_partially_reviewed(base)


def test_filters_are_triage_first_with_medal_subset():
    keys = [k for k, _ in FILTERS]
    labels = [lab for _, lab in FILTERS]
    assert keys[0] == "ALL"
    assert UNREVIEWED in keys
    assert IN_CATEGORY in keys and OUT_OF_CATEGORY in keys and UNCERTAIN in keys
    assert "Вне товарных категорий" in labels
    assert "GOLD" in labels and "Коммерчески не подходит" in labels
    assert any("Неинтересн" in lab for lab in labels)
    # Primary list no longer requires a separate "Проверено" pill.
    assert REVIEWED not in keys
