"""Tests for commercial-entry + medal staged annotation."""
from __future__ import annotations

from src.services.annotation_category_gate import (
    CATEGORY_SCOPE_FIELD,
    IN_CATEGORY,
    build_in_category_payload,
    build_out_of_category_payload,
)
from src.services.annotation_staged import (
    apply_subcategory_map,
    is_staged_complete,
    merge_staged_fields,
    staged_card_summary,
    subcategory_codes_of,
)
from src.services.expert_commercial_entry import (
    COMMERCIAL,
    COMMERCIAL_ENTRY_FIELD,
    NON_COMMERCIAL,
    UNCERTAIN as ENTRY_UNCERTAIN,
)
from src.services.expert_medal_stage import (
    BRONZE,
    GOLD,
    MEDAL_FIELD,
    MEDAL_SEMANTICS,
    SILVER,
    WOOD,
    medal_of,
)
from src.services.source_contour import LAW_223, resolve_source_contour


def _base_in(**kwargs):
    base = build_in_category_payload(
        assessment=None,
        created_by="t",
        category_codes=kwargs.pop("codes", ["waterproofing"]),
        category_names={"waterproofing": "Гидроизоляция"},
    )
    return merge_staged_fields(
        base,
        object_sector="RESIDENTIAL",
        object_type="APARTMENT_BUILDING",
        procurement_mode="WORKS",
        **kwargs,
    )


def test_out_of_category_does_not_require_commercial_or_medal():
    payload = merge_staged_fields(
        build_out_of_category_payload(assessment=None, created_by="t"),
        object_sector="SOCIAL",
        object_type="SCHOOL",
        procurement_mode="DIRECT_SUPPLY",
    )
    assert is_staged_complete(payload)
    assert payload.get(COMMERCIAL_ENTRY_FIELD) is None
    assert medal_of(payload) is None
    summary = staged_card_summary(payload)
    assert any("Вне товарных категорий" in line[1] for line in summary["lines"])


def test_in_category_requires_category_and_commercial_entry():
    incomplete = merge_staged_fields(
        build_in_category_payload(
            assessment=None, created_by="t", category_codes=["waterproofing"]
        ),
        object_sector="RESIDENTIAL",
        object_type="APARTMENT_BUILDING",
        procurement_mode="WORKS",
    )
    assert not is_staged_complete(incomplete)


def test_commercial_and_non_commercial_persist():
    commercial = _base_in(commercial_entry=COMMERCIAL, expert_medal=GOLD)
    assert commercial[COMMERCIAL_ENTRY_FIELD] == COMMERCIAL
    assert commercial[MEDAL_FIELD] == GOLD
    assert commercial.get("expert_commercial_verdict") == "ACTIONABLE"
    assert is_staged_complete(commercial)

    rejected = _base_in(commercial_entry=NON_COMMERCIAL)
    assert rejected[COMMERCIAL_ENTRY_FIELD] == NON_COMMERCIAL
    assert medal_of(rejected) is None
    assert rejected.get("expert_commercial_verdict") == "NO_COMMERCIAL_ENTRY"
    assert is_staged_complete(rejected)


def test_uncertain_commercial_persists_without_medal():
    payload = _base_in(commercial_entry=ENTRY_UNCERTAIN)
    assert payload[COMMERCIAL_ENTRY_FIELD] == ENTRY_UNCERTAIN
    assert medal_of(payload) is None
    assert is_staged_complete(payload)


def test_all_medals_persist():
    for medal in (GOLD, SILVER, BRONZE, WOOD):
        payload = _base_in(commercial_entry=COMMERCIAL, expert_medal=medal)
        assert payload[MEDAL_FIELD] == medal
        assert is_staged_complete(payload)
        assert medal in MEDAL_SEMANTICS


def test_commercial_allows_medal_non_commercial_does_not_require():
    with_medal = _base_in(commercial_entry=COMMERCIAL, expert_medal=SILVER)
    assert is_staged_complete(with_medal)
    without_medal = _base_in(commercial_entry=COMMERCIAL)
    assert not is_staged_complete(without_medal)
    non_com = _base_in(commercial_entry=NON_COMMERCIAL)
    assert is_staged_complete(non_com)


def test_subcategory_follows_selected_category():
    payload = _base_in(commercial_entry=COMMERCIAL, expert_medal=BRONZE)
    payload = apply_subcategory_map(
        payload, subcategory_by_category={"waterproofing": "injection_joints"}
    )
    assert subcategory_codes_of(payload) == ["injection_joints"]
    assert payload["opportunities"][0]["subcategory_code"] == "injection_joints"


def test_source_contour_not_confused_with_commercial_entry():
    contour = resolve_source_contour("reestr_contract_223_fz")
    assert contour["law_code"] == LAW_223
    payload = _base_in(commercial_entry=NON_COMMERCIAL)
    assert payload[COMMERCIAL_ENTRY_FIELD] == NON_COMMERCIAL
    assert "Корпоративная" in contour["contour_label"]


def test_legacy_medal_preserved_without_inventing_entry():
    legacy = {
        CATEGORY_SCOPE_FIELD: IN_CATEGORY,
        "expert_category_codes": ["X"],
        "expert_medal": GOLD,
        "expert_commercial_verdict": "ACTIONABLE",
        "expert_object_sector": "SOCIAL",
        "expert_object_type": "SCHOOL",
        "expert_procurement_mode": "WORKS",
    }
    assert medal_of(legacy) == GOLD
    assert legacy.get(COMMERCIAL_ENTRY_FIELD) is None
    assert not is_staged_complete(legacy)


def test_card_summary_uses_human_labels():
    payload = _base_in(commercial_entry=COMMERCIAL, expert_medal=GOLD)
    summary = staged_card_summary(
        payload, name_by_code={"waterproofing": "Гидроизоляция"}
    )
    joined = " ".join(v for _, v in summary["lines"])
    assert "Гидроизоляция" in joined
    assert "Коммерчески подходит" in joined
    assert "GOLD" in joined
    assert "IN_CATEGORY" not in joined
    assert "COMMERCIAL" not in joined


def test_non_commercial_summary():
    payload = _base_in(commercial_entry=NON_COMMERCIAL)
    summary = staged_card_summary(payload, name_by_code={"waterproofing": "Гидроизоляция"})
    joined = " ".join(v for _, v in summary["lines"])
    assert "Коммерчески не подходит" in joined
