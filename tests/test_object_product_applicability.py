"""OBJECT -> PRODUCT candidate layer (Layer 1) contract tests.

WIP OBJECT-PRODUCT-CANDIDATE-LAYER-IMPLEMENTATION-V1.

Covers only what this WIP added:
  * a single canonical OBJECT x PRODUCT applicability authority;
  * the procurement-mode gate (DIRECT / SERVICE_NO_OBJECT / AMBIGUOUS -> none);
  * canonical-object requirement (no classification inside the generator);
  * YES/CONDITIONAL -> candidate, UNKNOWN -> not promoted, NO -> never;
  * PIPE / internal-lighting overgeneration guards;
  * axis validation against product_ontology and human projection.
"""
from __future__ import annotations

from src.services import object_product_applicability as M
from src.services import product_ontology as PO


def _types(cands) -> set[str]:
    return {c["PRODUCT_TYPE"] for c in cands}


def _axes(cands) -> set[tuple[str, str, str | None, str | None, str | None]]:
    return {
        (c["PRODUCT_FAMILY"], c["PRODUCT_TYPE"], c["APPLICATION"], c["MATERIAL"], c["VARIANT"])
        for c in cands
    }


def test_matrix_is_valid_and_has_expected_shape() -> None:
    assert M.validate_matrix() == ()
    stats = M.matrix_stats()
    assert stats["relations"] == len(M.relations()) > 0
    assert set(stats["by_applicability"]) <= set(PO.APPLICABILITY_VALUES)


def test_matrix_authority_is_this_module() -> None:
    assert M.MATRIX_AUTHORITY.endswith("src/services/object_product_applicability.py")
    assert M.CANDIDATE_MODEL_VERSION == "object_product_v1"
    assert M.CANDIDATE_STATUS_PRE_EVIDENCE == "PRE_EVIDENCE"


def test_relations_are_distinct() -> None:
    keys = [r.key() for r in M.relations()]
    assert len(keys) == len(set(keys))


def test_every_relation_uses_canonical_axes() -> None:
    for rel in M.relations():
        assert PO.validate_product_axes(
            family=rel.product_family,
            product_type=rel.product_type,
            application=rel.application,
            material=rel.material,
            variant=rel.variant,
        ) == ()
        assert rel.source in M.RELATION_SOURCE_VALUES
        assert rel.applicability in PO.APPLICABILITY_VALUES


def test_direct_mode_generates_nothing() -> None:
    assert M.generate_candidates(
        "DIRECT", object_sector="INFRASTRUCTURE", object_type="BRIDGE"
    ) == []
    assert M.candidate_generation_enabled("DIRECT") is False


def test_service_no_object_mode_generates_nothing() -> None:
    assert M.generate_candidates(
        "SERVICE_NO_OBJECT", object_sector="INFRASTRUCTURE", object_type="BRIDGE"
    ) == []


def test_ambiguous_mode_generates_nothing() -> None:
    assert M.generate_candidates(
        "AMBIGUOUS", object_sector="INFRASTRUCTURE", object_type="BRIDGE"
    ) == []


def test_unknown_or_missing_mode_generates_nothing() -> None:
    assert M.generate_candidates(None, object_type="BRIDGE") == []
    assert M.generate_candidates("WAT", object_type="BRIDGE") == []


def test_invalid_object_generates_nothing() -> None:
    # a good, not an object; free text is not accepted either
    assert M.generate_candidates("OBJECT", object_type="BENCH") == []
    assert M.generate_candidates("OBJECT", object_type="??????? ???") == []
    assert M.generate_candidates("OBJECT") == []
    # sector must agree with the canonical owner of the object type
    assert M.generate_candidates(
        "OBJECT", object_sector="SOCIAL", object_type="BRIDGE"
    ) == []
    # subtype must belong to the object type
    assert M.generate_candidates(
        "OBJECT", object_sector="INFRASTRUCTURE", object_type="ROAD", object_subtype="NEW_BUILD"
    ) == []


def test_road_candidate_set() -> None:
    cands = M.generate_candidates("OBJECT", object_sector="INFRASTRUCTURE", object_type="ROAD")
    assert len(cands) == len(_axes(cands))  # deduplicated
    assert {"LIGHTING_FIXTURE", "LIGHTING_POLE", "DRAINAGE_TRAY", "ROAD_BARRIER",
            "RAILING", "STORM_WATER_INLET"} <= _types(cands)
    assert all(c["CANDIDATE_STATUS"] == "PRE_EVIDENCE" for c in cands)
    assert all(c["CANDIDATE_MODEL_VERSION"] == M.CANDIDATE_MODEL_VERSION for c in cands)


def test_bridge_candidate_set() -> None:
    cands = M.generate_candidates("OBJECT", object_sector="INFRASTRUCTURE", object_type="BRIDGE")
    axes = _axes(cands)
    assert ("BARRIER_RAILING", "RAILING", None, "COMPOSITE", None) in axes
    assert ("LIGHTING", "LIGHTING_POLE", None, "METAL", None) in axes
    assert ("DRAINAGE", "DRAINAGE_TRAY", None, None, None) in axes
    assert ("PIPES", "PIPE", "BRIDGE", None, None) in axes


def test_tunnel_excludes_lighting_pole() -> None:
    cands = M.generate_candidates("OBJECT", object_sector="INFRASTRUCTURE", object_type="TUNNEL")
    assert "LIGHTING_FIXTURE" in _types(cands)
    assert "LIGHTING_POLE" not in _types(cands)
    assert M.applicability_for(
        object_sector="INFRASTRUCTURE", object_type="TUNNEL",
        product_family="LIGHTING", product_type="LIGHTING_POLE", material="METAL",
    ) == "NO"


def test_utility_network_pipe_is_accepted() -> None:
    for subtype in ("WATER_NETWORK", "GAS_NETWORK"):
        cands = M.generate_candidates(
            "OBJECT", object_sector="INFRASTRUCTURE", object_type="UTILITY_NETWORKS",
            object_subtype=subtype,
        )
        pipes = [c for c in cands if c["PRODUCT_TYPE"] == "PIPE"]
        assert pipes, subtype
        assert all(c["APPLICABILITY"] == "YES" for c in pipes)


def test_internal_building_pipe_is_not_generated_from_parent_object() -> None:
    for object_type, sector in (
        ("APARTMENT_BUILDING", "RESIDENTIAL"),
        ("OFFICE", "COMMERCIAL"),
        ("SCHOOL", "SOCIAL"),
    ):
        cands = M.generate_candidates("OBJECT", object_sector=sector, object_type=object_type)
        assert "PIPE" not in _types(cands), object_type


def test_road_pipe_is_conditional_not_general() -> None:
    cands = M.generate_candidates("OBJECT", object_sector="INFRASTRUCTURE", object_type="ROAD")
    pipes = [c for c in cands if c["PRODUCT_TYPE"] == "PIPE"]
    assert pipes, "culvert PIPE relation must exist for ROAD"
    assert all(c["APPLICABILITY"] == "CONDITIONAL" for c in pipes)
    assert all(c["APPLICATION"] in (None, "ROAD") for c in pipes)


def test_conditional_lighting_pole_relations() -> None:
    for sector, object_type in (("URBAN_IMPROVEMENT", "COURTYARD"), ("RESIDENTIAL", "APARTMENT_BUILDING")):
        cands = M.generate_candidates("OBJECT", object_sector=sector, object_type=object_type)
        poles = [c for c in cands if c["PRODUCT_TYPE"] == "LIGHTING_POLE"]
        assert poles, object_type
        assert all(c["APPLICABILITY"] == "CONDITIONAL" for c in poles)


def test_unknown_is_not_promoted_by_default() -> None:
    strict = M.generate_candidates("OBJECT", object_sector="COMMERCIAL", object_type="PARKING")
    assert "LIGHTING_POLE" not in _types(strict)
    assert M.applicability_for(
        object_sector="COMMERCIAL", object_type="PARKING",
        product_family="LIGHTING", product_type="LIGHTING_POLE", material="METAL",
    ) == "UNKNOWN"
    diagnostic = M.generate_candidates(
        "OBJECT", object_sector="COMMERCIAL", object_type="PARKING", include_unknown=True
    )
    assert any(c["PRODUCT_TYPE"] == "LIGHTING_POLE" and c["APPLICABILITY"] == "UNKNOWN"
               for c in diagnostic)


def test_no_relation_ever_generates_a_candidate() -> None:
    no_relations = [r for r in M.relations() if r.applicability == "NO"]
    assert no_relations
    for rel in no_relations:
        cands = M.generate_candidates(
            "OBJECT", object_sector=rel.object_sector, object_type=rel.object_type,
            object_subtype=rel.object_subtype, include_unknown=True,
        )
        assert rel.product_type not in _types(cands), rel.key()


def test_no_unknown_candidate_has_confidence_status() -> None:
    for rel in M.relations():
        assert not (rel.applicability == "UNKNOWN" and rel.is_candidate)


def test_unresolved_relations_remain_available_for_diagnostics() -> None:
    unresolved = M.unresolved_relations()
    assert len(unresolved) == M.matrix_stats()["by_applicability"].get("UNKNOWN", 0)
    assert all(r.applicability == "UNKNOWN" for r in unresolved)


def test_all_product_types_have_at_least_one_relation() -> None:
    used = {r.product_type for r in M.relations()}
    assert used == set(PO.PRODUCT_TYPE_VALUES)
    for rel in M.relations():
        assert PO.family_of_product_type(rel.product_type) == rel.product_family


def test_human_projection_does_not_create_new_product_types() -> None:
    cands = M.generate_candidates("OBJECT", object_sector="INFRASTRUCTURE", object_type="BRIDGE")
    projected = M.user_projection(cands)
    assert len(projected) == len(cands)
    labels = {row["USER_LABEL"] for row in projected}
    assert labels
    for row, label in zip(projected, labels):
        assert row["PRODUCT_TYPE"] in PO.PRODUCT_TYPE_VALUES
    composite = [r for r in projected
                 if r["PRODUCT_TYPE"] == "RAILING" and r["MATERIAL"] == "COMPOSITE"]
    assert composite and "\u043a\u043e\u043c\u043f\u043e\u0437\u0438\u0442" in composite[0]["USER_LABEL"].lower()


def test_procurement_mode_gate_matrix() -> None:
    assert M.candidate_generation_enabled("OBJECT") is True
    for off in ("DIRECT", "SERVICE_NO_OBJECT", "AMBIGUOUS", "", None, "OTHER"):
        assert M.candidate_generation_enabled(off) is False
