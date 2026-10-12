"""Canonical PRODUCT_FAMILY / PRODUCT_TYPE / APPLICATION / MATERIAL / VARIANT /
TECHNOLOGY contract.

WIP=PRODUCT-ONTOLOGY-CANONICAL-IMPLEMENTATION-V1.

Covers only what this WIP added:
  * single canonical source: src/services/product_ontology.py;
  * 5 families / 12 types / 16 applications / 4 materials / 2 variants / 0 tech;
  * PRODUCT_TYPE belongs to exactly one family, impossible pairs rejected;
  * COMPOSITES is not a family and COMPOSITE is a material, never a type;
  * object-typed legacy lighting values are APPLICATION, not product types;
  * drainage product vs application vs variant are not mixed;
  * UNKNOWN applicability is valid; DIRECT disables product candidates;
  * the ontology is a semantic layer separate from crm_product_categories.
"""
from __future__ import annotations

import pathlib

import pytest

from src.services import product_ontology as P

AUTHORITY = pathlib.Path(P.__file__).resolve()
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

CANONICAL_FAMILIES = (
    "LIGHTING",
    "BARRIER_RAILING",
    "DRAINAGE",
    "PIPES",
    "GRATING_AND_DECKING",
)

LIGHTING_LEGACY_APPLICATION = {
    "ROAD_LIGHTING": "ROAD",
    "STREET_LIGHTING": "STREET",
    "PARK_LIGHTING": "PARK",
    "TUNNEL_LIGHTING": "TUNNEL",
    "PARKING_LIGHTING": "PARKING",
    "FACADE_LIGHTING": "FACADE",
    "INDUSTRIAL_LIGHTING": "INDUSTRIAL",
    "URBAN_LIGHTING": "OTHER_URBAN",
}


# ---------------------------------------------------------------- families
def test_canonical_family_set_is_exact() -> None:
    assert tuple(P.PRODUCT_FAMILY_VALUES) == CANONICAL_FAMILIES


def test_composites_is_not_a_product_family() -> None:
    assert not P.is_canonical_product_family("COMPOSITES")
    assert "COMPOSITES" not in P.PRODUCT_FAMILY_VALUES


def test_every_product_type_belongs_to_exactly_one_family() -> None:
    seen: set[str] = set()
    for family in P.PRODUCT_FAMILY_VALUES:
        types = P.types_of_family(family)
        assert types, f"{family} has no product types"
        for product_type in types:
            assert product_type not in seen, f"{product_type} declared twice"
            seen.add(product_type)
            assert P.family_of_product_type(product_type) == family
    assert seen == set(P.PRODUCT_TYPE_VALUES)


def test_every_application_not_product_type() -> None:
    for application in P.APPLICATION_VALUES:
        assert not P.is_canonical_product_type(application)


# ------------------------------------------------------------- vocabularies
def test_all_product_types_are_canonical() -> None:
    assert len(P.PRODUCT_TYPE_VALUES) == 12
    for product_type in P.PRODUCT_TYPE_VALUES:
        assert P.is_canonical_product_type(product_type)
        assert P.is_canonical_product_family(P.family_of_product_type(product_type))


def test_all_application_values_are_canonical() -> None:
    assert len(P.APPLICATION_VALUES) == 16
    assert tuple(P.APPLICATION_VALUES) == tuple(dict.fromkeys(P.APPLICATION_VALUES))
    for application in P.APPLICATION_VALUES:
        assert P.is_canonical_application(application)


def test_all_material_values_are_canonical() -> None:
    assert len(P.MATERIAL_VALUES) == 4
    for material in P.MATERIAL_VALUES:
        assert P.is_canonical_material(material)
    assert "COMPOSITE" in P.MATERIAL_VALUES


def test_unconfirmed_materials_are_not_canonical() -> None:
    for material in P.UNCONFIRMED_MATERIALS:
        assert not P.is_canonical_material(material)
    assert not P.is_canonical_material("POLYMER_CONCRETE")
    assert not P.is_canonical_material("POLYMER_SAND")


def test_all_variant_values_are_canonical() -> None:
    assert tuple(P.VARIANT_VALUES) == ("LINEAR", "WELL")
    for variant in P.VARIANT_VALUES:
        assert P.is_canonical_variant(variant)
        assert not P.is_canonical_product_type(variant)


def test_technology_registry_is_empty() -> None:
    assert P.TECHNOLOGY_VALUES == ()
    for candidate in P.RESERVED_TECHNOLOGY_CANDIDATES:
        assert candidate == "LED"
        assert not P.is_canonical_technology(candidate)
        assert not P.is_canonical_material(candidate)
        assert not P.is_canonical_product_type(candidate)


# -------------------------------------------------------------- migrations
def test_legacy_migration_covers_all_28_discovery_values() -> None:
    assert len(P.LEGACY_PRODUCT_MIGRATIONS) == 28
    assert len(P.LEGACY_DISCOVERY_VALUES) == 28


def test_legacy_migration_decision_counts() -> None:
    counts = P.legacy_migration_counts()
    assert counts["TOTAL"] == 28
    assert counts[P.MOVE_TO_APPLICATION] == 12
    assert counts[P.MOVE_TO_MATERIAL] == 3
    assert counts[P.MOVE_TO_VARIANT] == 2
    assert counts[P.KEEP_AS_PRODUCT_TYPE] == 8
    assert counts[P.RENAME] == 2
    assert counts[P.DROP_AS_FALSE_SIGNAL] == 1


def test_every_legacy_migration_is_valid() -> None:
    assert P.validate_legacy_migrations() == ()


def test_unknown_legacy_value_returns_none() -> None:
    assert P.migrate_legacy_product("NOT_A_DISCOVERY_VALUE") is None


def test_dropped_legacy_value_has_no_axes() -> None:
    migrated = P.migrate_legacy_product("DRAINAGE_CHANNEL")
    assert migrated is not None
    assert migrated["dropped"] is True
    assert migrated["product_type"] is None


def test_lighting_decomposition() -> None:
    for legacy, application in LIGHTING_LEGACY_APPLICATION.items():
        assert not P.is_canonical_product_type(legacy)
        migrated = P.migrate_legacy_product(legacy)
        assert migrated is not None
        assert migrated["product_family"] == "LIGHTING"
        assert migrated["product_type"] == "LIGHTING_FIXTURE"
        assert migrated["application"] == application
        assert P.is_canonical_application(migrated["application"])


def test_barrier_railing_decomposition() -> None:
    bridge_barrier = P.migrate_legacy_product("BRIDGE_BARRIER")
    assert bridge_barrier is not None
    assert bridge_barrier["product_type"] == "ROAD_BARRIER"
    assert bridge_barrier["application"] == "BRIDGE"

    bridge_railing = P.migrate_legacy_product("BRIDGE_RAILING")
    assert bridge_railing is not None
    assert bridge_railing["product_type"] == "RAILING"
    assert bridge_railing["application"] == "BRIDGE"

    assert not P.is_canonical_product_type("BRIDGE_BARRIER")
    assert not P.is_canonical_product_type("BRIDGE_RAILING")
    assert not P.is_canonical_product_type("PEDESTRIAN_RAILING")
    assert not P.is_canonical_product_type("STREET_RAILING")


def test_drainage_decomposition() -> None:
    for legacy, application in (("ROAD_DRAINAGE", "ROAD"), ("BRIDGE_DRAINAGE", "BRIDGE")):
        migrated = P.migrate_legacy_product(legacy)
        assert migrated is not None
        assert migrated["product_type"] == "DRAINAGE_TRAY"
        assert migrated["application"] == application
        assert not P.is_canonical_product_type(legacy)

    linear = P.migrate_legacy_product("LINEAR_DRAINAGE")
    assert linear is not None
    assert linear["product_type"] == "DRAINAGE_TRAY"
    assert linear["variant"] == "LINEAR"

    well = P.migrate_legacy_product("DRAINAGE_WELL")
    assert well is not None
    assert well["product_type"] == "STORM_WATER_INLET"
    assert well["variant"] == "WELL"


def test_composite_decomposition() -> None:
    assert not P.is_canonical_product_family("COMPOSITES")
    assert not P.is_canonical_product_type("COMPOSITE_RAILING")
    assert not P.is_canonical_product_type("COMPOSITE_DRAINAGE_TRAY")
    assert not P.is_canonical_product_type("COMPOSITE_PIPE")

    railing = P.migrate_legacy_product("COMPOSITE_RAILING")
    assert railing is not None
    assert (railing["product_type"], railing["material"]) == ("RAILING", "COMPOSITE")

    tray = P.migrate_legacy_product("COMPOSITE_DRAINAGE_TRAY")
    assert tray is not None
    assert (tray["product_type"], tray["material"]) == ("DRAINAGE_TRAY", "COMPOSITE")

    pipe = P.migrate_legacy_product("COMPOSITE_PIPE")
    assert pipe is not None
    assert pipe["product_type"] == "PIPE"
    assert "COMPOSITE" in P.LEGACY_PRODUCT_MIGRATIONS["COMPOSITE_PIPE"].material_options


# ------------------------------------------------------------- validation
def test_invalid_axis_combinations_rejected() -> None:
    assert P.validate_product_axes(family="LIGHTING", product_type="RAILING")
    assert P.validate_product_axes(family="DRAINAGE", product_type="LIGHTING_FIXTURE")
    assert P.validate_product_axes(
        family="LIGHTING", product_type="LIGHTING_FIXTURE", application="ROOF"
    )
    assert P.validate_product_axes(
        family="LIGHTING", product_type="LIGHTING_FIXTURE", material="LED"
    )
    assert P.validate_product_axes(family="", product_type="")
    assert P.validate_product_axes(
        family="LIGHTING", product_type="LIGHTING_FIXTURE", technology="LED"
    )


def test_valid_axis_combinations_accepted() -> None:
    assert P.validate_product_axes(family="LIGHTING", product_type="LIGHTING_FIXTURE") == ()
    assert P.validate_product_axes(
        family="BARRIER_RAILING", product_type="RAILING", application="BRIDGE", material="COMPOSITE"
    ) == ()
    assert P.validate_product_axes(
        family="DRAINAGE", product_type="DRAINAGE_TRAY", variant="LINEAR", material="CONCRETE"
    ) == ()


def test_normalize_product_axes_raises_on_bad_pair() -> None:
    with pytest.raises(P.ProductOntologyError):
        P.normalize_product_axes(family="LIGHTING", product_type="RAILING")


def test_unknown_applicability_is_valid_and_kept() -> None:
    assert P.is_valid_applicability("UNKNOWN")
    assert P.is_valid_applicability("YES")
    assert P.is_valid_applicability("CONDITIONAL")
    assert P.is_valid_applicability("NO")
    assert not P.is_valid_applicability("MAYBE")


# ------------------------------------------------------------------ DIRECT
def test_direct_disables_product_candidate_generation() -> None:
    assert P.product_candidate_generation_allowed("DIRECT") is False
    assert P.product_candidate_generation_allowed("direct") is False
    assert P.product_candidate_generation_allowed("OBJECT") is True
    assert P.product_candidate_generation_allowed("SERVICE_NO_OBJECT") is True


# -------------------------------------------------------------- projection
def test_user_facing_projection_examples() -> None:
    label = P.user_facing_label(product_type="LIGHTING_FIXTURE", application="ROAD")
    assert label == "Дорожное освещение"
    label = P.user_facing_label(product_type="LIGHTING_FIXTURE", application="PARK")
    assert label == "Парковое освещение"
    label = P.user_facing_label(product_type="LIGHTING_FIXTURE", application="TUNNEL")
    assert label == "Тоннельное освещение"
    assert (
        P.user_facing_label(
            product_type="RAILING", application="BRIDGE", material="COMPOSITE"
        )
        == "Композитное мостовое перильное ограждение"
    )


def test_projection_does_not_create_product_types() -> None:
    label = P.user_facing_label(
        product_type="DRAINAGE_TRAY", application="BRIDGE", material="CONCRETE"
    )
    assert label
    assert not P.is_canonical_product_type(label)


# ------------------------------------------------------- architecture rules
def test_ontology_is_separate_from_crm_category_registry() -> None:
    import_lines = [
        line.strip()
        for line in AUTHORITY.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    imported = " ".join(import_lines)
    for forbidden in (
        "crm_product_categories",
        "product_subcategory_seed_data",
        "product_subcategories_service",
        "category_registry_service",
        "commercial_taxonomy_registry",
    ):
        assert forbidden not in imported
    from src.services import product_subcategory_seed_data as seeds

    crm_category_codes = {seed["category_code"] for seed in seeds.CATEGORY_SEEDS}
    assert {"lighting", "composites", "drainage_water_management"} <= crm_category_codes
    assert not (crm_category_codes & set(P.PRODUCT_FAMILY_VALUES))


def test_regex_is_candidate_only() -> None:
    assert P.REGEX_AUTHORITY == "FIND_CANDIDATE_ONLY"
    assert set(P.OBJECT_PATTERNS_FORBIDDEN_AS_PRIOR) == {"SOCIAL_CARE", "ENERGY_FACILITY", "STREET"}


def test_stats_match_contract_counts() -> None:
    assert P.ontology_stats() == {
        "product_families": 5,
        "product_types": 12,
        "application_values": 16,
        "material_values": 4,
        "variant_values": 2,
        "technology_values": 0,
    }
