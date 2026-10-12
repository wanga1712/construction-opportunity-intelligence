"""Layer 1 production materialization contract (storage + object-source policy).

WIP PRODUCT-CANDIDATE-LAYER-PRODUCTION-V1.

Covers only what this WIP added on top of the frozen matrix:
  * the migration artifact shape for crm_procurement_product_candidates;
  * procurement-mode gate before any object work;
  * the OBJECT SOURCE POLICY allow-list (free text / regex never confirms);
  * canonical-object validation via expert_object_taxonomy;
  * YES/CONDITIONAL materialized, UNKNOWN parked, NO never generated;
  * the write invariants and the idempotency identity.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.services import product_candidate_materializer as M
from src.services import product_ontology as PO

MIGRATION = Path("src/migrations/crm_procurement_product_candidates_1.sql")

REQUIRED_COLUMNS = (
    "procurement_id",
    "procurement_mode",
    "object_sector",
    "object_type",
    "object_subtype",
    "object_context",
    "product_family",
    "product_type",
    "application",
    "material",
    "variant",
    "technology",
    "applicability",
    "candidate_status",
    "candidate_source",
    "candidate_version",
    "is_current",
    "created_at",
    "updated_at",
)


def _signal(source="EXPERT_CONFIRMED", sector="INFRASTRUCTURE", otype="ROAD", subtype=None, pid=1):
    return M.ObjectSignal(pid, source, sector, otype, subtype)


# ---------------------------------------------------------------- storage spec
def test_migration_is_additive_and_idempotent() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS crm_procurement_product_candidates" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uix_cppc_identity" in sql
    assert "NULLS NOT DISTINCT" in sql
    assert "DROP CONSTRAINT IF EXISTS" in sql
    assert "ALTER TABLE crm_procurements" not in sql
    assert "DROP TABLE" not in sql.upper()


def test_migration_declares_required_columns_and_grants() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    for column in REQUIRED_COLUMNS:
        assert re.search(rf"^\s*{column}\s", sql, re.M), column
    assert "REFERENCES crm_procurements(id)" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON crm_procurement_product_candidates TO crm_app" in sql
    assert "USAGE, SELECT ON SEQUENCE crm_procurement_product_candidates_id_seq" in sql


def _ddl_only(text: str) -> str:
    """Strip -- comments so prose cannot satisfy or break a DDL assertion."""
    return "\n".join(
        line.split("--", 1)[0] for line in text.splitlines()
    ).lower()


def test_migration_has_no_medal_or_opportunity_surface() -> None:
    ddl = _ddl_only(MIGRATION.read_text(encoding="utf-8"))
    for banned in ("medal", "gold", "silver", "bronze", "opportunity_id", "crm_category"):
        assert banned not in ddl, banned


def test_migration_guards_canonical_status_and_applicability() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CHECK (candidate_status = 'PRE_EVIDENCE')" in sql
    assert "'YES', 'CONDITIONAL', 'NO', 'UNKNOWN'" in sql


# ------------------------------------------------------- procurement mode gate
def test_scope_type_maps_to_canonical_mode() -> None:
    assert M.resolve_procurement_mode("DIRECT_GOODS") == PO.PROCUREMENT_MODE_DIRECT
    assert M.resolve_procurement_mode("WORKS_WITH_EMBEDDED_PRODUCTS") == PO.PROCUREMENT_MODE_OBJECT
    assert M.resolve_procurement_mode("PURE_SERVICE") == PO.PROCUREMENT_MODE_SERVICE_NO_OBJECT
    assert M.resolve_procurement_mode("DESIGN_PROJECT") == PO.PROCUREMENT_MODE_AMBIGUOUS


def test_unknown_scope_type_is_not_a_mode() -> None:
    for value in ("UNKNOWN", "", None, "SOMETHING_NEW"):
        assert M.resolve_procurement_mode(value) is None


def test_mode_gate_precedes_object_work() -> None:
    # A perfect object cannot unlock a non-OBJECT mode.
    for mode in ("DIRECT", "SERVICE_NO_OBJECT", "AMBIGUOUS", "", None):
        assert M.build_candidates(mode, _signal()) == []


def test_direct_purchase_of_apartment_has_no_candidates() -> None:
    signal = M.ObjectSignal(48036, "EXPERT_CONFIRMED", "RESIDENTIAL", "RESIDENTIAL_UNIT")
    assert M.build_candidates("DIRECT", signal) == []
    eligible, reason = M.candidate_eligibility("DIRECT", M.OBJECT_STATUS_RESOLVED)
    assert eligible is False and reason == M.SKIP_DIRECT


# ---------------------------------------------------------- object source policy
def test_object_source_allow_list_is_explicit() -> None:
    assert M.ALLOWED_OBJECT_SOURCES == (
        "REVIEWED",
        "EXPERT_CONFIRMED",
        "CANONICAL_CURRENT",
        "DETERMINISTIC_HIGH_CONFIDENCE",
        "QWEN_OBJECT_V1",
    )
    # A Qwen *mode* answer proves nothing about the object: mode-only.
    assert M.MODE_ONLY_SOURCES == ("QWEN_MODE_V1",)
    assert not M.object_source_allowed("QWEN_MODE_V1")
    for source in M.ALLOWED_OBJECT_SOURCES:
        assert M.object_source_allowed(source)
    for source in ("REGEX_TITLE", "AI_BACKGROUND", "FREE_TEXT", "", None, "HIGH_CONFIDENCE_RULE_X"):
        assert not M.object_source_allowed(source), source


def test_free_text_object_never_confirms() -> None:
    text_signal = M.ObjectSignal(7, "REGEX_TITLE", "INFRASTRUCTURE", "ROAD", "ROAD_REPAIR")
    assessment = M.assess_object(text_signal)
    assert assessment.status == M.OBJECT_STATUS_NONCANONICAL
    assert M.build_candidates("OBJECT", text_signal) == []


def test_canonical_object_required() -> None:
    bogus = M.ObjectSignal(8, "EXPERT_CONFIRMED", "INFRASTRUCTURE", "NOT_A_REAL_OBJECT_TYPE")
    assert M.assess_object(bogus).status == M.OBJECT_STATUS_NONCANONICAL

    wrong_sector = M.ObjectSignal(9, "EXPERT_CONFIRMED", "SOCIAL", "ROAD")
    assert M.assess_object(wrong_sector).status == M.OBJECT_STATUS_UNRESOLVED

    bad_subtype = M.ObjectSignal(10, "EXPERT_CONFIRMED", "INFRASTRUCTURE", "ROAD", "WATER_NETWORK")
    assert M.assess_object(bad_subtype).status == M.OBJECT_STATUS_UNRESOLVED

    assert M.assess_object(None).status == M.OBJECT_STATUS_MISSING
    assert M.assess_object(M.ObjectSignal(11, "EXPERT_CONFIRMED")).status == M.OBJECT_STATUS_MISSING


def test_eligibility_skip_reasons_are_exhaustive() -> None:
    for status in M.OBJECT_STATUS_VALUES:
        for mode in ("DIRECT", "OBJECT", "SERVICE_NO_OBJECT", "AMBIGUOUS", "NOPE"):
            eligible, reason = M.candidate_eligibility(mode, status)
            if eligible:
                assert reason is None
                assert mode == "OBJECT" and status == M.OBJECT_STATUS_RESOLVED
            else:
                assert reason in M.SKIP_REASONS


# ------------------------------------------------------------- candidate output
def test_object_mode_yields_only_yes_and_conditional() -> None:
    rows = M.build_candidates("OBJECT", _signal())
    assert rows
    assert {r["APPLICABILITY"] for r in rows} <= {"YES", "CONDITIONAL"}
    assert {r["CANDIDATE_STATUS"] for r in rows} == {M.CANDIDATE_STATUS}
    assert {r["CANDIDATE_SOURCE"] for r in rows} == {M.CANDIDATE_SOURCE}
    assert {r["CANDIDATE_VERSION"] for r in rows} == {M.CANDIDATE_MODEL_VERSION}
    assert {r["PROCUREMENT_MODE"] for r in rows} == {"OBJECT"}


def test_unknown_relation_is_never_materialized() -> None:
    # BRIDGE -> LIGHTING_POLE_BASE_PROTECTOR is UNKNOWN in the frozen matrix.
    rows = M.build_candidates("OBJECT", _signal(otype="BRIDGE"))
    assert "LIGHTING_POLE_BASE_PROTECTOR" not in {r["PRODUCT_TYPE"] for r in rows}


def test_rejected_relation_is_never_materialized() -> None:
    # PARK -> ROAD_BARRIER is NO in the frozen matrix.
    rows = M.build_candidates("OBJECT", _signal(sector="URBAN_IMPROVEMENT", otype="PARK"))
    assert "ROAD_BARRIER" not in {r["PRODUCT_TYPE"] for r in rows}


def test_tunnel_excludes_lighting_pole() -> None:
    rows = M.build_candidates("OBJECT", _signal(otype="TUNNEL"))
    assert "LIGHTING_POLE" not in {r["PRODUCT_TYPE"] for r in rows}


def test_utility_network_water_yields_pipe() -> None:
    rows = M.build_candidates(
        "OBJECT", _signal(sector="INFRASTRUCTURE", otype="UTILITY_NETWORKS", subtype="WATER_NETWORK")
    )
    assert "PIPE" in {r["PRODUCT_TYPE"] for r in rows}


def test_building_internal_lighting_is_not_generated_from_parent_object() -> None:
    rows = M.build_candidates("OBJECT", _signal(sector="RESIDENTIAL", otype="APARTMENT_BUILDING"))
    assert "LIGHTING_FIXTURE" not in {r["PRODUCT_TYPE"] for r in rows}


def test_courtyard_lighting_pole_stays_conditional() -> None:
    rows = M.build_candidates("OBJECT", _signal(sector="URBAN_IMPROVEMENT", otype="COURTYARD"))
    poles = [r for r in rows if r["PRODUCT_TYPE"] == "LIGHTING_POLE"]
    assert poles and {r["APPLICABILITY"] for r in poles} == {"CONDITIONAL"}


def test_technology_is_never_set() -> None:
    rows = M.build_candidates("OBJECT", _signal())
    assert rows and all(r["TECHNOLOGY"] is None for r in rows)
    assert PO.TECHNOLOGY_VALUES == ()


# ------------------------------------------------------------------- invariants
def test_invariants_pass_for_generated_rows() -> None:
    assert M.verify_invariants(M.build_candidates("OBJECT", _signal())) == ()


def test_invariants_catch_mode_and_status_violations() -> None:
    good = M.build_candidates("OBJECT", _signal())
    bad_mode = dict(good[0], PROCUREMENT_MODE="DIRECT")
    assert any("outside OBJECT mode" in p for p in M.verify_invariants([bad_mode]))

    bad_status = dict(good[0], CANDIDATE_STATUS="CONFIRMED")
    assert any("candidate_status" in p for p in M.verify_invariants([bad_status]))

    bad_tech = dict(good[0], TECHNOLOGY="LED")
    assert any("TECHNOLOGY" in p for p in M.verify_invariants([bad_tech]))

    bad_app = dict(good[0], APPLICABILITY="UNKNOWN")
    assert any("APPLICABILITY" in p for p in M.verify_invariants([bad_app]))


def test_invariants_catch_duplicates_and_bad_axes() -> None:
    good = M.build_candidates("OBJECT", _signal())
    assert any("duplicate" in p for p in M.verify_invariants([good[0], good[0]]))
    bad_axes = dict(good[0], PRODUCT_TYPE="COMPOSITES", PRODUCT_FAMILY="COMPOSITES")
    assert M.verify_invariants([bad_axes])


def test_idempotency_identity_matches_storage_key() -> None:
    rows = M.dedupe_candidates(M.build_candidates("OBJECT", _signal()))
    identities = [M.candidate_identity(r) for r in rows]
    assert len(identities) == len(set(identities))
    doubled = M.dedupe_candidates(rows + rows)
    assert len(doubled) == len(rows)
    assert M.candidate_identity(rows[0])[1] == M.CANDIDATE_MODEL_VERSION


def test_composite_is_material_not_product_family() -> None:
    rows = M.build_candidates("OBJECT", _signal(otype="BRIDGE"))
    composites = [r for r in rows if r["MATERIAL"] == "COMPOSITE"]
    assert composites, "BRIDGE must expose at least one COMPOSITE relation"
    assert all(r["PRODUCT_FAMILY"] != "COMPOSITE" for r in rows)
    assert all(r["PRODUCT_TYPE"] != "COMPOSITES" for r in rows)


def test_materializer_stats_report_empty_technology_registry() -> None:
    stats = M.materializer_stats()
    assert stats["candidate_model_version"] == "object_product_v1"
    assert stats["candidate_status"] == "PRE_EVIDENCE"
    assert stats["candidate_source"] == "OBJECT_PRODUCT_MATRIX"
    assert stats["allowed_object_sources"] == list(M.ALLOWED_OBJECT_SOURCES)
    assert PO.TECHNOLOGY_VALUES == ()


def test_contract_counts_are_frozen() -> None:
    assert len(PO.PRODUCT_FAMILY_VALUES) == 5
    assert len(PO.PRODUCT_TYPE_VALUES) == 12
    assert len(PO.APPLICATION_VALUES) == 16
    assert len(PO.MATERIAL_VALUES) == 4
    assert len(PO.VARIANT_VALUES) == 2