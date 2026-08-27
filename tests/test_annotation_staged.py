"""Tests for staged object + procurement-mode annotation."""
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

    # Do not invent commercial from title-like tokens alone — only source_table.
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


def test_category_gate_preserved_with_staged_fields():
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
    )
    assert payload[CATEGORY_SCOPE_FIELD] == IN_CATEGORY
    assert payload["expert_category_codes"] == ["waterproofing"]
    assert is_staged_complete(payload)


def test_out_of_category_does_not_require_product_category():
    payload = merge_staged_fields(
        build_out_of_category_payload(assessment=None, created_by="t"),
        object_sector="INFRASTRUCTURE",
        object_type="ENERGY_INFRASTRUCTURE",
        procurement_mode=DIRECT_SUPPLY,
    )
    assert payload[CATEGORY_SCOPE_FIELD] == OUT_OF_CATEGORY
    assert payload["expert_category_codes"] == []
    assert is_staged_complete(payload)


def test_legacy_category_only_is_partial_not_fully_reviewed():
    payload = {CATEGORY_SCOPE_FIELD: OUT_OF_CATEGORY}
    assert is_partially_reviewed(payload)
    assert not is_staged_complete(payload)

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
    assert counts[REVIEWED] == 1
    assert counts[UNREVIEWED] == 2
    assert counts[OUT_OF_CATEGORY] == 2
    assert states[10]["is_partial"] is True
    assert states[11]["is_staged_complete"] is True


def test_structured_summary_hides_blanks_when_unreviewed():
    assert staged_card_summary(None)["status"] == "UNREVIEWED"
    assert staged_card_summary({})["lines"] == []
    summary = staged_card_summary(
        merge_staged_fields(
            build_out_of_category_payload(assessment=None, created_by="t"),
            object_sector="INDUSTRIAL",
            object_type="ENERGY_FACILITY",
            procurement_mode=DIRECT_SUPPLY,
        )
    )
    assert summary["status"] == "REVIEWED"
    assert any("Объект" in line[0] for line in summary["lines"])
    assert any("Формат" in line[0] for line in summary["lines"])


def test_uncertain_category_persists_without_fake_certainty():
    payload = merge_staged_fields(
        build_uncertain_payload(assessment=None, created_by="t"),
        object_sector="UNCERTAIN",
        object_type="UNCERTAIN_OBJECT",
        procurement_mode=MODE_UNCERTAIN,
    )
    assert payload[CATEGORY_SCOPE_FIELD] == UNCERTAIN
    assert is_staged_complete(payload)


def test_filters_include_category_secondary_without_dropping_legacy():
    keys = [k for k, _ in FILTERS]
    assert UNREVIEWED in keys and REVIEWED in keys
    assert IN_CATEGORY in keys and OUT_OF_CATEGORY in keys and UNCERTAIN in keys
