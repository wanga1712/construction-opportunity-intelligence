"""Canonical OBJECT_SECTOR / OBJECT_TYPE / OBJECT_SUBTYPE contract.

WIP OBJECT-TAXONOMY-CANONICAL-IMPLEMENTATION-V1.

Covers only what this WIP added or changed:
  * single canonical source: src/services/expert_object_taxonomy.py;
  * URBAN_IMPROVEMENT sector added; no TRANSPORT_/UTILITY_ duplicate sectors;
  * UTILITY_NETWORKS subtypes; legacy alias normalization (input only);
  * goods are NOT object types; DIRECT_SUPPLY -> object axes N/A;
  * OBJECT_CONTEXT extended while APPLICATION_AREA stays a separate axis;
  * routing/UI consumers emit canonical codes only.
"""
from __future__ import annotations

import pathlib

import pytest

from src.services import expert_object_taxonomy as T
from src.services.commercial_routing_v3.object_mode_routing import classify_object
from src.services.first_pass.resolver import resolve_object_family

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "src" / "migrations" / "commercial_taxonomy_object_context_terms_1.sql"

CANONICAL_SECTORS = (
    "SOCIAL",
    "RESIDENTIAL",
    "COMMERCIAL",
    "INDUSTRIAL",
    "INFRASTRUCTURE",
    "URBAN_IMPROVEMENT",
    "OTHER",
    "UNCERTAIN",
)


def test_canonical_sector_set_is_exact() -> None:
    assert tuple(T.OBJECT_SECTOR_VALUES) == CANONICAL_SECTORS


def test_no_duplicate_transport_or_utility_sector() -> None:
    for bad in ("TRANSPORT_INFRASTRUCTURE", "UTILITY_INFRASTRUCTURE", "CONSTRUCTION"):
        assert not T.is_canonical_sector(bad)


def test_urban_improvement_types_are_objects_not_goods() -> None:
    types = set(T.types_of_sector(T.URBAN_IMPROVEMENT))
    assert {"PARK", "SQUARE", "COURTYARD", "EMBANKMENT", "PUBLIC_SPACE",
            "PEDESTRIAN_ZONE", "STREETSCAPE", "PLAYGROUND", "GREEN_AREA",
            "OTHER_URBAN_IMPROVEMENT"} <= types
    for goods in ("BENCH", "URN", "MAF", "LIGHTING_POLE", "PLAYGROUND_EQUIPMENT",
                  "CURBSTONE", "DRAINAGE"):
        assert goods not in types
        assert not T.is_canonical_object_type(goods)


def test_removed_object_types_stay_absent() -> None:
    for gone in ("HEALTHCARE", "SANATORIUM", "UTILITY_PLANT"):
        assert not T.is_canonical_object_type(gone)


def test_expected_new_types_present() -> None:
    for code in ("DISPENSARY", "UNIVERSITY", "SOCIAL_CARE"):
        assert T.sector_of_object_type(code) == T.SOCIAL
    assert T.sector_of_object_type("RESIDENTIAL_UNIT") == T.RESIDENTIAL
    assert T.sector_of_object_type("PARKING") == T.COMMERCIAL
    assert T.sector_of_object_type("INDUSTRIAL_SITE") == T.INDUSTRIAL
    for code in ("STREET", "TUNNEL", "INTERCHANGE", "RAILWAY", "AIRPORT", "TRANSPORT_HUB"):
        assert T.sector_of_object_type(code) == T.INFRASTRUCTURE


def test_utility_network_subtypes() -> None:
    assert {c for c, _ in T.object_subtype_options("UTILITY_NETWORKS")} == {
        "HEATING_NETWORK", "WATER_NETWORK", "SEWER_NETWORK",
        "POWER_NETWORK", "GAS_NETWORK", "COMMUNICATION_NETWORK",
    }
    assert T.sector_of_object_type("UTILITY_NETWORKS") == T.INFRASTRUCTURE


@pytest.mark.parametrize(
    "legacy, sector, otype, subtype",
    [
        ("TRANSPORT_INFRASTRUCTURE", "INFRASTRUCTURE", None, None),
        ("ROAD_INFRASTRUCTURE", "INFRASTRUCTURE", "ROAD", None),
        ("BRIDGE_INFRASTRUCTURE", "INFRASTRUCTURE", "BRIDGE", None),
        ("UTILITY_INFRASTRUCTURE", "INFRASTRUCTURE", "UTILITY_NETWORKS", None),
        ("SOCIAL_INFRASTRUCTURE", "SOCIAL", None, None),
        ("SOCIAL_OBJECTS", "SOCIAL", None, None),
        ("HEALTHCARE", "SOCIAL", None, None),
        ("GENERAL_CONSTRUCTION", "OTHER", "OTHER_OBJECT", None),
        ("GAS_PIPELINE", "INFRASTRUCTURE", "UTILITY_NETWORKS", "GAS_NETWORK"),
        ("BUILDING_OR_STRUCTURE", "OTHER", "OTHER_OBJECT", None),
        ("road_infrastructure", "INFRASTRUCTURE", "ROAD", None),
    ],
)
def test_legacy_aliases_normalize_never_emit(legacy, sector, otype, subtype) -> None:
    # A legacy sector name may arrive in either the sector or the type slot.
    for axes in (T.normalize_object_axes(sector=legacy),
                 T.normalize_object_axes(object_type=legacy)):
        assert axes[T.OBJECT_SECTOR_FIELD] == sector
        assert axes[T.OBJECT_TYPE_FIELD] == otype
        assert axes[T.OBJECT_SUBTYPE_FIELD] == subtype
    assert not T.is_canonical_sector(legacy)


@pytest.mark.parametrize(
    "free_text, sector, otype, subtype",
    [
        ("дорога", "INFRASTRUCTURE", "ROAD", None),
        ("улица", "INFRASTRUCTURE", "STREET", None),
        ("мост", "INFRASTRUCTURE", "BRIDGE", None),
        ("теплосеть", "INFRASTRUCTURE", "UTILITY_NETWORKS", "HEATING_NETWORK"),
        ("водопровод", "INFRASTRUCTURE", "UTILITY_NETWORKS", "WATER_NETWORK"),
        ("мкд", "RESIDENTIAL", "APARTMENT_BUILDING", None),
        ("школа", "SOCIAL", "SCHOOL", None),
        ("поликлиника", "SOCIAL", "POLYCLINIC", None),
    ],
)
def test_db_free_text_normalizes(free_text, sector, otype, subtype) -> None:
    axes = T.normalize_object_axes(object_type=free_text)
    assert (axes[T.OBJECT_SECTOR_FIELD], axes[T.OBJECT_TYPE_FIELD],
            axes[T.OBJECT_SUBTYPE_FIELD]) == (sector, otype, subtype)


def test_unknown_input_never_fabricates_codes() -> None:
    axes = T.normalize_object_axes(object_type="неведомый объект")
    assert axes[T.OBJECT_TYPE_FIELD] is None
    assert axes[T.OBJECT_SECTOR_FIELD] is None


def test_direct_supply_object_axes_are_not_applicable() -> None:
    axes = T.object_axes_for_direct_supply()
    assert axes[T.OBJECT_SECTOR_FIELD] == T.OBJECT_NOT_APPLICABLE
    assert axes[T.OBJECT_TYPE_FIELD] == T.OBJECT_NOT_APPLICABLE
    assert axes[T.OBJECT_SUBTYPE_FIELD] == T.OBJECT_NOT_APPLICABLE
    assert T.object_axes_not_applicable("DIRECT_GOODS_PURCHASE")
    assert not T.object_axes_not_applicable("CONSTRUCTION_WORKS")


def test_object_context_extended_and_application_area_separate() -> None:
    ctx = {c.lower() for c, _ in T.object_context_terms()}
    assert {"landscaping", "courtyard", "external_territory", "parking_area"} <= ctx
    area = {c.lower() for c, _ in T.application_area_terms()}
    assert {"roof", "basement", "facade"} <= area
    # A part-of-object (roof) is never an OBJECT_CONTEXT; a territory is never an area.
    assert "roof" in area
    assert "landscaping" not in area


def test_routing_emits_canonical_object_codes_only() -> None:
    road = classify_object({"title": "Ремонт автомобильной дороги", "okpd_code": "42.11"},
                           form="CONSTRUCTION_WORKS")
    assert (road["object_sector"], road["object_type"]) == (T.INFRASTRUCTURE, "ROAD")

    school = classify_object({"title": 'Капитальный ремонт школы №6'}, form="CONSTRUCTION_WORKS")
    assert (school["object_sector"], school["object_type"]) == (T.SOCIAL, "SCHOOL")

    hospice = classify_object({"title": "Ремонт терапевтического корпуса больницы"},
                             form="CONSTRUCTION_WORKS")
    assert hospice["object_sector"] == T.SOCIAL
    assert hospice["object_type"] == "HOSPITAL"

    disp = classify_object({"title": "Ремонт онкологического диспансера"},
                           form="CONSTRUCTION_WORKS")
    assert disp["object_type"] == "DISPENSARY"

    unknown = classify_object({"title": "Выполнение прочих работ"}, form="CONSTRUCTION_WORKS")
    assert unknown["object_sector"] == T.UNCERTAIN
    assert T.is_canonical_object_type(unknown["object_type"])

    for payload in (road, school, hospice, disp, unknown):
        assert T.is_canonical_sector(payload["object_sector"])
        assert T.is_canonical_object_type(payload["object_type"])
        sub = payload.get("object_subtype")
        if sub:
            assert T.is_canonical_object_subtype(sub, payload["object_type"])

    # Direct supply never invents an object.
    for form in ("DIRECT_GOODS_PURCHASE",):
        direct = classify_object({"title": "Поставка картриджей"}, form=form)
        assert direct["object_sector"] in (T.UNCERTAIN, T.OTHER)


def test_first_pass_family_derives_from_canonical_taxonomy() -> None:
    assert resolve_object_family(object_type="ROAD") == "COMMERCIAL"
    assert resolve_object_family(sector="SOCIAL", object_type="SCHOOL") == "SOCIAL"
    assert resolve_object_family(object_type="DISPENSARY") == "SOCIAL"
    assert resolve_object_family(object_type="UTILITY_NETWORKS") == "COMMERCIAL"
    assert resolve_object_family(sector="URBAN_IMPROVEMENT") == "COMMERCIAL"
    assert resolve_object_family(sector="OTHER", object_type="OTHER_OBJECT") == "OTHER"
    assert resolve_object_family(scope_type="DIRECT_GOODS") == "DIRECT_SUPPLY"


def test_object_context_migration_is_additive_and_idempotent() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    assert "INSERT INTO crm_taxonomy_dimensions" in text
    assert "ON CONFLICT (dimension_type, dimension_code) DO UPDATE" in text
    upper = text.upper()
    assert "DROP " not in upper and "RENAME " not in upper and "DELETE " not in upper
    assert "OBJECT_CONTEXT" in text and "APPLICATION_AREA" in text



# --- WIP OBJECT-TAXONOMY-GAP-IMPLEMENTATION-V1 -------------------------------


def test_social_college_added_as_canonical_type() -> None:
    assert T.is_canonical_object_type("COLLEGE", T.SOCIAL)
    assert T.sector_of_object_type("COLLEGE") == T.SOCIAL
    assert {"SCHOOL", "COLLEGE", "UNIVERSITY"} <= set(T.types_of_sector(T.SOCIAL))
    assert T.object_type_label("COLLEGE")
    assert not T.is_canonical_object_type("COLLEGE", T.COMMERCIAL)


def test_no_admin_building_or_industrial_warehouse_type() -> None:
    for absent in ("ADMIN_BUILDING", "ADMINISTRATIVE_BUILDING",
                   "VOCATIONAL_EDUCATION", "EDUCATION_OTHER"):
        assert not T.is_canonical_object_type(absent)
    # WAREHOUSE stays COMMERCIAL; there is no INDUSTRIAL/WAREHOUSE.
    assert T.sector_of_object_type("WAREHOUSE") == T.COMMERCIAL
    assert not T.is_canonical_object_type("WAREHOUSE", T.INDUSTRIAL)


@pytest.mark.parametrize(
    "raw, sector, otype, subtype",
    [
        ("LIBRARY", "SOCIAL", "CULTURE_FACILITY", None),
        ("TECHNICUM", "SOCIAL", "COLLEGE", None),
        ("VOCATIONAL_SCHOOL", "SOCIAL", "COLLEGE", None),
        ("SPO", "SOCIAL", "COLLEGE", None),
        ("POLYCLINIC", "SOCIAL", "POLYCLINIC", None),
        ("DISPENSARY", "SOCIAL", "DISPENSARY", None),
        ("CABLE_LINE", "INFRASTRUCTURE", "UTILITY_NETWORKS", "POWER_NETWORK"),
        ("OVERHEAD_POWER_LINE", "INFRASTRUCTURE", "UTILITY_NETWORKS", "POWER_NETWORK"),
        ("HEATING_MAIN", "INFRASTRUCTURE", "UTILITY_NETWORKS", "HEATING_NETWORK"),
        ("HEATING_PIPELINE", "INFRASTRUCTURE", "UTILITY_NETWORKS", "HEATING_NETWORK"),
    ],
)
def test_gap_implementation_safe_aliases(raw, sector, otype, subtype) -> None:
    # A legacy name may arrive in either the sector or the type slot.
    for axes in (T.normalize_object_axes(object_type=raw),
                 T.normalize_object_axes(sector=raw)):
        assert (axes[T.OBJECT_SECTOR_FIELD], axes[T.OBJECT_TYPE_FIELD],
                axes[T.OBJECT_SUBTYPE_FIELD]) == (sector, otype, subtype)
    # legacy input only: never itself a canonical sector code
    assert not T.is_canonical_sector(raw)


@pytest.mark.parametrize(
    "raw, sector, otype, subtype",
    [
        ("библиотека", "SOCIAL", "CULTURE_FACILITY", None),
        ("колледж", "SOCIAL", "COLLEGE", None),
        ("техникум", "SOCIAL", "COLLEGE", None),
        ("спо", "SOCIAL", "COLLEGE", None),
        ("диспансер", "SOCIAL", "DISPENSARY", None),
        ("кабельная линия", "INFRASTRUCTURE", "UTILITY_NETWORKS", "POWER_NETWORK"),
        ("тепломагистраль", "INFRASTRUCTURE", "UTILITY_NETWORKS", "HEATING_NETWORK"),
    ],
)
def test_gap_implementation_russian_free_text(raw, sector, otype, subtype) -> None:
    # Russian free text arrives in the object_type slot (legacy DB free text).
    axes = T.normalize_object_axes(object_type=raw)
    assert (axes[T.OBJECT_SECTOR_FIELD], axes[T.OBJECT_TYPE_FIELD],
            axes[T.OBJECT_SUBTYPE_FIELD]) == (sector, otype, subtype)
    assert not T.is_canonical_sector(raw)
    assert not T.is_canonical_object_type(raw)


def test_network_alias_targets_subtype_never_context() -> None:
    ctx = {c.lower() for c, _ in T.object_context_terms()}
    for net in ("POWER_NETWORK", "HEATING_NETWORK", "WATER_NETWORK",
                "SEWER_NETWORK", "GAS_NETWORK", "COMMUNICATION_NETWORK"):
        assert T.is_canonical_object_subtype(net, "UTILITY_NETWORKS")
        assert net.lower() not in ctx


def test_contextually_ambiguous_terms_are_not_aliases() -> None:
    for term in ("ADMINISTRATIVE_BUILDING", "PUMPING_STATION",
                 "TREATMENT_PLANT", "PLAYGROUND"):
        assert term in T.CONTEXTUAL_BOUNDARY_EXAMPLES, term
    for term in ("ADMINISTRATIVE_BUILDING", "PUMPING_STATION",
                 "TREATMENT_PLANT", "PLAYGROUND_TERM"):
        assert term not in T.LEGACY_OBJECT_ALIASES
        assert term.lower() not in T.LEGACY_RUSSIAN_OBJECT_TYPES
    # No silent resolution from context-free input.
    for raw in ("administrative building", "ADMINISTRATIVE_BUILDING",
                "pumping station", "PUMPING_STATION",
                "treatment plant", "TREATMENT_PLANT"):
        axes = T.normalize_object_axes(object_type=raw)
        assert axes[T.OBJECT_TYPE_FIELD] is None
        assert axes[T.OBJECT_SECTOR_FIELD] is None


def test_playground_stays_an_object_type_not_a_term_alias() -> None:
    assert T.sector_of_object_type("PLAYGROUND") == T.URBAN_IMPROVEMENT
    assert T.is_canonical_object_type("PLAYGROUND")
    assert "PLAYGROUND_TERM" not in T.LEGACY_OBJECT_ALIASES
    assert T.CONTEXTUAL_BOUNDARY_EXAMPLES["PLAYGROUND"]


def test_semantic_boundary_tables_cover_adjacent_codes() -> None:
    bounds = T.OBJECT_SEMANTIC_BOUNDARIES
    for code in ("OFFICE", "SOCIAL_ADMIN", "WAREHOUSE", "FACTORY",
                 "PRODUCTION_BUILDING", "INDUSTRIAL_SITE", "ENERGY_FACILITY",
                 "UTILITY_NETWORKS", "MUNICIPAL_INFRASTRUCTURE",
                 "PARK", "SQUARE", "COURTYARD", "PUBLIC_SPACE",
                 "PEDESTRIAN_ZONE", "STREETSCAPE", "PLAYGROUND", "GREEN_AREA"):
        assert code in bounds, code
        assert T.is_canonical_object_type(code), code
        assert bounds[code].strip()
    rules = " ".join(T.OBJECT_VS_CONTEXT_RULES)
    assert "HEATING_NETWORK" in rules
    assert "OBJECT_CONTEXT=COURTYARD" in rules


def test_taxonomy_stats_after_college_addition() -> None:
    stats = T.taxonomy_stats()
    assert stats["sectors"] == 8
    assert stats["types"] == 53
    assert stats["subtypes"] == 13
    assert len(T.types_of_sector(T.SOCIAL)) == 12
