"""CRM V3 S13 database canonicalization readiness tests (local, no production writes)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.services.commercial_routing_v3.legacy_okpd_knowledge import (
    LEGACY_STOP_HARD_SKIP,
    LEGACY_STOP_SIGNAL_STRENGTH,
    SUPPLEMENTAL_EXPERT_PROVENANCE,
    build_migration_bundle,
    build_stop_word_bundle,
    load_audit_json,
    rules_from_audit_json,
)
from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db
from src.services.commercial_routing_v3.schema_readiness import check_v3_schema_readiness
from src.services.db_role_contract import (
    ENV_KEYS_TO_CHANGE_FOR_CUTOVER,
    PROPOSED_S13_CRM_DB_NAME,
    PROPOSED_S13_CRM_DB_ROLE,
    assert_no_tender_monitor_write_in_v3,
    assert_v3_writes_target_crm_only,
    resolve_db_role_contract,
)
from tests.test_v3_schema_readiness import FakeCrmDb

ROOT = Path(__file__).resolve().parents[1]
AUDIT_JSON = ROOT / "data" / "legacy_okpd_audit_raw.json"
V3_DIR = ROOT / "src" / "services" / "commercial_routing_v3"


class TestSourceCrmDsnSeparation:
    def test_source_and_crm_can_point_to_different_servers(self) -> None:
        contract = resolve_db_role_contract(
            {
                "TENDER_MONITOR_DB_HOST": "10.8.0.7",
                "TENDER_MONITOR_DB_PORT": "5432",
                "TENDER_MONITOR_DB_DATABASE": "tender_monitor",
                "TENDER_MONITOR_DB_USER": "reader",
                "CRM_DB_HOST": "127.0.0.1",
                "CRM_DB_PORT": "5432",
                "CRM_DB_DATABASE": "crm",
                "CRM_DB_USER": "crm_app",
            }
        )
        assert contract.source_role_explicit is True
        assert contract.crm_role_explicit is True
        assert contract.same_server is False
        assert contract.same_database is False
        assert contract.roles_separated is True
        assert contract.source.route == "10.8.0.7:5432/tender_monitor"
        assert contract.crm.route == "127.0.0.1:5432/crm"

    def test_ambiguous_generic_fallback_rejected(self) -> None:
        contract = resolve_db_role_contract(
            {
                "TENDER_MONITOR_DB_HOST": "10.8.0.7",
                "TENDER_MONITOR_DB_DATABASE": "tender_monitor",
                "TENDER_MONITOR_DB_USER": "reader",
                # CRM host missing → would implicitly reuse source host
            }
        )
        assert contract.ambiguous_generic_fallback is True
        assert contract.roles_separated is False

    def test_current_like_same_server_different_databases_ok(self) -> None:
        contract = resolve_db_role_contract(
            {
                "TENDER_MONITOR_DB_HOST": "10.8.0.7",
                "TENDER_MONITOR_DB_PORT": "5432",
                "TENDER_MONITOR_DB_DATABASE": "tender_monitor",
                "TENDER_MONITOR_DB_USER": "postgres",
                "CRM_DB_HOST": "10.8.0.7",
                "CRM_DB_PORT": "5432",
                "CRM_DB_DATABASE": "crm",
                "CRM_DB_USER": "postgres",
            }
        )
        assert contract.same_server is True
        assert contract.same_database is False
        assert contract.source_role_explicit is True
        assert contract.crm_role_explicit is True


class TestV3SchemaReadinessCrmOnly:
    def test_readiness_checks_crm_db_tables_only(self) -> None:
        db = FakeCrmDb(
            tables={
                "crm_category_okpd_priors": {"id"},
                "crm_category_routing_signals": {"id"},
                "crm_procurement_category_opportunities": {
                    "id",
                    "commercial_state",
                    "last_source_event",
                    "last_source_seen_at",
                    "source_missing_since",
                    "source_sync_status",
                    "opportunity_track",
                    "commercial_priority_score",
                    "research_value_score",
                },
                "crm_category_opportunity_lifecycle_audit": {"id"},
                "crm_legacy_okpd_migration_audit": {"id"},
                "crm_product_categories": {
                    "category_code",
                    "category_name",
                    "description",
                    "is_active",
                    "sort_order",
                    "semantic_type",
                    "lifecycle_state",
                    "searchability_mode",
                },
            }
        )
        r = check_v3_schema_readiness(db)
        assert r.ready is True
        assert not any("tender_monitor" in m for m in r.missing)
        assert not any("reestr_contract" in m for m in r.missing)

    def test_missing_legacy_audit_blocks_readiness(self) -> None:
        db = FakeCrmDb(
            tables={
                "crm_category_okpd_priors": {"id"},
                "crm_category_routing_signals": {"id"},
                "crm_procurement_category_opportunities": {
                    "id",
                    "commercial_state",
                    "last_source_event",
                    "last_source_seen_at",
                    "source_missing_since",
                    "source_sync_status",
                    "opportunity_track",
                    "commercial_priority_score",
                    "research_value_score",
                },
                "crm_category_opportunity_lifecycle_audit": {"id"},
                "crm_product_categories": {
                    "category_code",
                    "category_name",
                    "description",
                    "is_active",
                    "sort_order",
                    "semantic_type",
                    "lifecycle_state",
                    "searchability_mode",
                },
            }
        )
        r = check_v3_schema_readiness(db)
        assert r.ready is False
        assert any("crm_legacy_okpd_migration_audit" in m for m in r.missing)


class TestWriteTargets:
    def test_v3_writes_use_crm_role(self) -> None:
        assert_v3_writes_target_crm_only("crm_db")
        with pytest.raises(AssertionError):
            assert_v3_writes_target_crm_only("source_db")

    def test_no_v3_code_writes_to_tender_monitor(self) -> None:
        for path in V3_DIR.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            # Static: V3 package must not emit source-mutating SQL fragments.
            for fragment in (
                "INSERT INTO reestr_contract_",
                "UPDATE reestr_contract_",
                "INTO okpd_from_users",
                "INTO collection_codes_okpd",
            ):
                assert fragment.lower() not in text.lower(), path
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if any(
                        x in node.value.lower()
                        for x in ("insert into reestr_contract_", "update reestr_contract_")
                    ):
                        raise AssertionError(f"{path}: source write SQL literal")
            assert_no_tender_monitor_write_in_v3(text)

    def test_okpd_prior_loader_has_no_user_id_filter(self) -> None:
        src = Path(load_okpd_priors_from_db.__code__.co_filename).read_text(encoding="utf-8")
        # Narrow: the loader SQL must not filter by user_id.
        assert "WHERE active = TRUE" in src or "where active = true" in src.lower()
        assert "user_id =" not in src.lower().replace("source_user_id", "")


class TestSupplementalAndStopProvenance:
    def test_supplemental_priors_not_mislabeled_as_legacy(self) -> None:
        if not AUDIT_JSON.exists():
            pytest.skip("audit extract missing")
        raw = load_audit_json(AUDIT_JSON)
        bundle = build_migration_bundle(rules_from_audit_json(raw))
        supplemental = [
            p
            for p in bundle.priors
            if p.okpd_pattern in {"27.40", "27.32"}
            and p.commercial_category_code in {"lighting", "cable_support_systems"}
            and p.source_table == "supplemental_expert_rule"
        ]
        assert supplemental
        for p in supplemental:
            assert p.provenance == SUPPLEMENTAL_EXPERT_PROVENANCE
            assert p.provenance != "LEGACY_USER_SETTING"
            assert "legacy" not in p.provenance.lower() or "supplemental" in p.provenance.lower()
            assert p.provenance == "SUPPLEMENTAL_EXPERT_RULE"

    def test_legacy_stop_signals_remain_soft(self) -> None:
        assert LEGACY_STOP_HARD_SKIP is False
        signals, _, counts = build_stop_word_bundle(
            [{"id": 1, "user_id": 1, "stop_word": "асфальтобетонных", "setting_id": 1}]
        )
        assert counts["NEGATIVE_SIGNAL"] == 1
        assert counts.get("GLOBAL_HARD_EXCLUSION", 0) == 0
        assert signals[0].signal_type == "NEGATIVE_SIGNAL"
        assert signals[0].signal_strength == LEGACY_STOP_SIGNAL_STRENGTH


class TestCutoverConfigContract:
    def test_proposed_s13_names(self) -> None:
        assert PROPOSED_S13_CRM_DB_NAME == "crm"
        assert PROPOSED_S13_CRM_DB_ROLE == "crm_app"
        assert "CRM_DB_HOST" in ENV_KEYS_TO_CHANGE_FOR_CUTOVER
        assert "CRM_DB_DATABASE" in ENV_KEYS_TO_CHANGE_FOR_CUTOVER
