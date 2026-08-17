"""Tests for COMMERCIAL-ROUTING-V3-LEGACY-OKPD-CATEGORY-KNOWLEDGE-1."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.commercial_taxonomy import COMMERCIAL_KEEP_CODES
from src.services.commercial_routing_v3.legacy_okpd_knowledge import (
    OKPD_CODE_SOURCE,
    PRIOR_WEIGHT_MODEL,
    LegacyOkpdRule,
    build_migration_bundle,
    build_stop_word_bundle,
    classify_legacy_rule,
    load_audit_json,
    multi_category_okpd_count,
    rules_from_audit_json,
)
from src.services.commercial_routing_v3.okpd_priors import (
    load_okpd_priors_from_db,
    match_okpd_priors,
    prefix_matches,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT_JSON = ROOT / "data" / "legacy_okpd_audit_raw.json"
STOP_JSON = ROOT / "data" / "legacy_stop_words_raw.json"


@pytest.fixture(scope="module")
def audit_raw() -> dict:
    return load_audit_json(AUDIT_JSON)


@pytest.fixture(scope="module")
def legacy_rules(audit_raw: dict):
    return rules_from_audit_json(audit_raw)


@pytest.fixture(scope="module")
def migration_bundle(legacy_rules):
    return build_migration_bundle(legacy_rules)


class TestLegacyOkpdExtraction:
    def test_legacy_okpd_extraction(self, audit_raw: dict, legacy_rules) -> None:
        assert audit_raw["rules_total"] == 338
        assert len(legacy_rules) == 338
        assert all(r.source_table == "okpd_from_users" for r in legacy_rules)

    def test_okpd_sub_code_source_documented(self) -> None:
        assert OKPD_CODE_SOURCE == "collection_codes_okpd.sub_code"


class TestOkpdMatching:
    def test_exact_matching(self) -> None:
        assert prefix_matches("42.11.20.900", "42.11.20.900", "EXACT")
        assert not prefix_matches("42.11.20.901", "42.11.20.900", "EXACT")

    def test_prefix_matching(self) -> None:
        assert prefix_matches("42.11.20.900", "42.11", "PREFIX")
        assert prefix_matches("42.11", "42.11", "PREFIX")
        assert not prefix_matches("142.11.20.900", "42.11", "PREFIX")
        assert not prefix_matches("42.110", "42.11", "PREFIX")

    def test_multi_category_per_okpd(self, migration_bundle) -> None:
        priors = [
            {
                "commercial_category_code": "lighting",
                "okpd_pattern": "42.11",
                "match_type": "PREFIX",
                "prior_weight": 50,
                "active": True,
            },
            {
                "commercial_category_code": "waterproofing",
                "okpd_pattern": "42.11",
                "match_type": "PREFIX",
                "prior_weight": 40,
                "active": True,
            },
        ]
        matched = match_okpd_priors("42.11.20.900", priors)
        cats = {m["commercial_category_code"] for m in matched}
        assert cats == {"lighting", "waterproofing"}
        assert multi_category_okpd_count(migration_bundle.priors) > 0


class TestRuntimeIndependence:
    def test_runtime_user_okpd_dependency_removed(self) -> None:
        sql = Path("src/services/commercial_routing_v3/okpd_priors.py").read_text(encoding="utf-8")
        query = sql.lower().split("from crm_category_okpd_priors", 1)[1]
        assert "where user_id" not in query
        assert "user_id =" not in query

    def test_user_id_provenance_preserved(self, migration_bundle) -> None:
        assert any(p.source_user_id is not None for p in migration_bundle.priors)

    def test_load_okpd_priors_from_db_has_no_user_filter(self) -> None:
        class FakeDb:
            captured_sql = ""

            def execute_query(self, sql, params=None):
                FakeDb.captured_sql = sql
                return []

        load_okpd_priors_from_db(FakeDb())
        lowered = FakeDb.captured_sql.lower()
        assert "where user_id" not in lowered
        assert "user_id =" not in lowered


class TestInvariants:
    def test_okpd_prior_not_document_proof(self) -> None:
        priors = [
            {
                "commercial_category_code": "lighting",
                "okpd_pattern": "27.40",
                "match_type": "PREFIX",
                "prior_weight": 70,
                "signal_role": "CANDIDATE_SIGNAL",
                "active": True,
            }
        ]
        matched = match_okpd_priors("27.40.25.123", priors)
        assert matched
        assert matched[0]["signal_role"] == "CANDIDATE_SIGNAL"

    def test_okpd_prior_not_ai_whitelist(self, migration_bundle) -> None:
        # Priors do not remove categories from registry; multiple categories per OKPD allowed.
        prepared = {p.commercial_category_code for p in migration_bundle.priors}
        assert prepared.issubset(COMMERCIAL_KEEP_CODES)
        assert multi_category_okpd_count(migration_bundle.priors) > 0

    def test_okpd_prior_not_matcher_whitelist(self) -> None:
        assert PRIOR_WEIGHT_MODEL.startswith("DISCRETE_EXPERT_SCALE")


class TestClassificationSafety:
    def test_context_only_not_commercial_category(self) -> None:
        rule = LegacyOkpdRule(
            legacy_rule_id=1,
            source_table="okpd_from_users",
            source_user_id=1,
            source_profile_id=1,
            okpd_code="71.12",
            okpd_prefix="71.12",
            match_semantics="PREFIX",
            include_exclude="INCLUDE",
            legacy_category="Проектирование",
            description=None,
        )
        cls, target, _ = classify_legacy_rule(rule, {"71.12"})
        assert cls == "CONTEXT_ONLY"
        assert target is None

    def test_material_family_not_blind_commercial_category(self) -> None:
        rule = LegacyOkpdRule(
            legacy_rule_id=392,
            source_table="okpd_from_users",
            source_user_id=1,
            source_profile_id=3,
            okpd_code="22.23.19.110",
            okpd_prefix="22.23.19.110",
            match_semantics="PREFIX",
            include_exclude="INCLUDE",
            legacy_category="Компьютеры",
            description="polymer composites",
        )
        cls, target, reason = classify_legacy_rule(rule, {"22.23.19.110"})
        assert cls == "REVIEW_REQUIRED"
        assert target == "composite_structures"
        assert "miscategorized" in (reason or "")

    def test_legacy_exclusions_not_blind_hard_filter(self) -> None:
        stop_rows = [{"id": 1, "user_id": 1, "stop_word": "асфальтобетонных", "setting_id": 1}]
        signals, _, counts = build_stop_word_bundle(stop_rows)
        assert counts["NEGATIVE_SIGNAL"] == 1
        assert all(s.signal_type == "NEGATIVE_SIGNAL" for s in signals)
        assert counts.get("GLOBAL_HARD_EXCLUSION", 0) == 0

    def test_legacy_stop_default_negative_signal(self) -> None:
        if not STOP_JSON.exists():
            pytest.skip("stop words export missing")
        raw = STOP_JSON.read_bytes()
        text = raw.decode("utf-16" if raw.startswith(b"\xff\xfe") else "utf-8")
        rows = json.loads(text).get("stop_all") or []
        signals, _, counts = build_stop_word_bundle(rows[:50])
        assert counts["NEGATIVE_SIGNAL"] == len({r["stop_word"].strip().lower() for r in rows[:50] if r.get("stop_word")})
        assert signals


class TestMigrationAudit:
    def test_migration_audit_complete(self, migration_bundle) -> None:
        assert len(migration_bundle.audit_rows) >= 338
        assert migration_bundle.classification_counts["MIGRATE_CONFIDENT"] > 0
        assert migration_bundle.classification_counts["CONTEXT_ONLY"] > 0


class TestProcurementPreviews:
    @pytest.fixture(scope="class")
    def generated_priors(self, migration_bundle):
        return [
            {
                "commercial_category_code": p.commercial_category_code,
                "okpd_pattern": p.okpd_pattern,
                "match_type": p.match_type,
                "prior_weight": p.prior_weight,
                "signal_role": p.signal_role,
                "active": True,
            }
            for p in migration_bundle.priors
        ]

    def test_1282_prior_preview(self, generated_priors) -> None:
        matched = match_okpd_priors("42.11.20.900", generated_priors)
        cats = sorted({m["commercial_category_code"] for m in matched})
        assert "lighting" in cats
        assert "waterproofing" in cats
        assert len(cats) >= 3

    def test_direct_lighting_prior_coverage(self, generated_priors) -> None:
        matched = match_okpd_priors("27.40.25.123", generated_priors)
        assert any(m["commercial_category_code"] == "lighting" for m in matched)

    def test_direct_computers_prior_coverage(self, generated_priors) -> None:
        matched = match_okpd_priors("26.20.17.110", generated_priors)
        assert any(m["commercial_category_code"] == "computers" for m in matched)
