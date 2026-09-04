"""Unit and integration tests for Superuser Research Taxonomy Service and Repository."""

from __future__ import annotations

import json
import os
import tempfile
import pytest

from src.models.taxonomy_rules import (
    MODE_BOOST,
    MODE_DOWNWEIGHT,
    MODE_EXCLUDE_FROM_PRIMARY,
    MODE_EXPLORE,
    MODE_NEUTRAL,
    PROPOSAL_STATUS_APPROVED,
    PROPOSAL_STATUS_PENDING,
    PROPOSAL_STATUS_REJECTED,
    TaxonomyAuditLogDTO,
    TaxonomyProposalDTO,
    TaxonomyRuleDTO,
)
from src.repositories.taxonomy_repository import TaxonomyRepository
from src.services.taxonomy_service import TaxonomyService
from src.learning.okpd_prior.combined_v2 import ResearchPriorityModelV2
from src.learning.okpd_prior.text_baseline import TitleTextBaselineV2
from src.learning.okpd_prior.semantic_model import TitleSemanticModelV2
from src.learning.okpd_prior.disambiguation import extract_domain_signals


def test_taxonomy_rule_dto_serialization():
    rule = TaxonomyRuleDTO(
        rule_id="r1",
        okpd_pattern="42.11.20",
        rule_mode=MODE_BOOST,
        adjustment_weight=0.30,
        reason="Road construction",
        created_by="admin",
        created_at="2026-09-04T12:00:00Z",
        is_active=True,
    )
    d = rule.to_dict()
    assert d["rule_id"] == "r1"
    assert d["adjustment_weight"] == 0.30

    reconstructed = TaxonomyRuleDTO.from_dict(d)
    assert reconstructed.okpd_pattern == "42.11.20"
    assert reconstructed.is_active is True


def test_taxonomy_proposal_dto_serialization():
    prop = TaxonomyProposalDTO(
        proposal_id="p1",
        okpd_pattern="26.20",
        proposed_mode=MODE_DOWNWEIGHT,
        proposed_adjustment=-0.25,
        evidence_summary="0 hits across 10 tenders",
        positive_count=0,
        negative_count=10,
        sample_pids=[101, 102, 103],
    )
    d = prop.to_dict()
    assert d["proposal_id"] == "p1"
    assert len(d["sample_pids"]) == 3

    reconstructed = TaxonomyProposalDTO.from_dict(d)
    assert reconstructed.negative_count == 10


def test_repository_file_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = os.path.join(tmpdir, "test_taxonomy.json")
        repo = TaxonomyRepository(storage_path=storage_path)

        rule = TaxonomyRuleDTO(
            rule_id="r100",
            okpd_pattern="43.99",
            rule_mode=MODE_EXPLORE,
            adjustment_weight=0.15,
            reason="Special construction exploration",
            created_by="superuser",
            created_at="2026-09-04T12:00:00Z",
            is_active=True,
        )
        repo.upsert_rule(rule)

        # Reload in a new repository instance
        repo2 = TaxonomyRepository(storage_path=storage_path)
        loaded_rule = repo2.get_rule_by_id("r100")
        assert loaded_rule is not None
        assert loaded_rule.okpd_pattern == "43.99"
        assert loaded_rule.rule_mode == MODE_EXPLORE


def test_service_longest_prefix_order():
    service = TaxonomyService(TaxonomyRepository(storage_path=None))

    # Add 4 levels of rules
    service.create_or_update_rule("42", MODE_BOOST, 0.10, "Level 1")
    service.create_or_update_rule("42.11", MODE_BOOST, 0.20, "Level 2")
    service.create_or_update_rule("42.11.20", MODE_BOOST, 0.30, "Level 3")
    service.create_or_update_rule("42.11.20.200", MODE_BOOST, 0.40, "Level 4")

    assert service.find_matching_rule("42.11.20.200").adjustment_weight == 0.40
    assert service.find_matching_rule("42.11.20.100").adjustment_weight == 0.30
    assert service.find_matching_rule("42.11.99").adjustment_weight == 0.20
    assert service.find_matching_rule("42.99.00").adjustment_weight == 0.10
    assert service.find_matching_rule("26.20") is None


def test_service_score_clamping():
    service = TaxonomyService(TaxonomyRepository(storage_path=None))
    service.create_or_update_rule("42", MODE_BOOST, 0.50, "Heavy boost")
    service.create_or_update_rule("10", MODE_DOWNWEIGHT, -0.80, "Heavy downweight")

    # Clamped to 1.0
    res_boost = service.compute_adjusted_priority(0.80, "42.11")
    assert res_boost["final_shadow_score"] == 1.0

    # Clamped to 0.0
    res_down = service.compute_adjusted_priority(0.30, "10.11")
    assert res_down["final_shadow_score"] == 0.0


def test_service_proposal_rejection():
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)

    prop = TaxonomyProposalDTO(
        proposal_id="prop_rej_1",
        okpd_pattern="26.30",
        proposed_mode=MODE_DOWNWEIGHT,
        proposed_adjustment=-0.25,
        evidence_summary="Negative cluster",
        positive_count=0,
        negative_count=5,
        sample_pids=[1, 2, 3],
    )
    repo.save_proposal(prop)

    success = service.reject_proposal("prop_rej_1", actor="admin")
    assert success is True
    updated = repo.get_all_proposals()
    assert updated[0].status == PROPOSAL_STATUS_REJECTED


def test_service_rule_deletion():
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)

    rule = service.create_or_update_rule("43.21", MODE_BOOST, 0.25, "Electrical")
    assert repo.get_rule_by_id(rule.rule_id) is not None

    deleted = service.delete_rule(rule.rule_id, actor="admin")
    assert deleted is True
    assert repo.get_rule_by_id(rule.rule_id) is None


def test_exploration_band_guarantee():
    service = TaxonomyService(TaxonomyRepository(storage_path=None))
    service.create_or_update_rule("43.99", MODE_EXPLORE, 0.20, "Exploration candidate")

    res = service.compute_adjusted_priority(0.35, "43.99.10")
    assert res["rule_mode"] == MODE_EXPLORE
    assert res["taxonomy_adjustment"] == 0.20
    assert res["final_shadow_score"] == 0.55


def test_exclude_from_primary_mode():
    service = TaxonomyService(TaxonomyRepository(storage_path=None))
    service.create_or_update_rule("31.01", MODE_EXCLUDE_FROM_PRIMARY, -0.60, "Office furniture exclude")

    res = service.compute_adjusted_priority(0.50, "31.01.10")
    assert res["rule_mode"] == MODE_EXCLUDE_FROM_PRIMARY
    assert res["taxonomy_adjustment"] == -0.60
    assert res["final_shadow_score"] == 0.0


def test_text_baseline_save_load_roundtrip():
    titles = [
        "Ремонт мостового полотна",
        "Поставка шприцев стерильных",
        "Гидроизоляция фундамента здания",
        "Закупка серверов",
    ]
    y = [1, 0, 1, 0]
    model = TitleTextBaselineV2().fit(titles, y)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "text_model.pkl")
        model.save_artifact(path)

        loaded = TitleTextBaselineV2.load_artifact(path)
        assert loaded.is_fitted
        p = loaded.predict_proba(["Ремонт моста", "Поставка шприцев"])
        assert p[0] > p[1]


def test_combined_v2_save_load_roundtrip():
    titles = [
        "Ремонт мостового полотна",
        "Поставка шприцев стерильных",
        "Гидроизоляция фундамента здания",
        "Закупка серверов",
        "Монтаж кровельного покрытия",
        "Поставка канцелярских товаров",
    ]
    okpds = ["42.11", "32.50", "43.99", "26.20", "43.91", "17.23"]
    prices = [1000000.0, 50000.0, 3000000.0, 500000.0, 2000000.0, 20000.0]
    y = [1, 0, 1, 0, 1, 0]

    model = ResearchPriorityModelV2().fit(titles, okpds, prices, y, dataset_snapshot_sha256="test_sha_v2")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "combined_v2.pkl")
        model.save_artifact(path)

        loaded = ResearchPriorityModelV2.load_artifact(path)
        assert loaded.is_fitted
        p = loaded.predict_proba(["Ремонт кровли", "Закупка бумаги"], ["43.91", "17.23"], [1500000.0, 10000.0])
        assert p[0] > p[1]


def test_medical_risk_suppression_lowers_priority():
    sig = extract_domain_signals("Поставка шприцев инъекционных одноразовых медицинских", "32.50.13")
    assert sig["medical_risk"] >= 0.8
    assert sig["disambiguated_injection_score"] == -1.0


def test_works_vs_goods_signal_difference():
    sig_w = extract_domain_signals("Выполнение работ по капитальному ремонту фасада", "41.20")
    sig_g = extract_domain_signals("Поставка товаров и мебели", "31.09")
    assert sig_w["works_signal"] > sig_g["works_signal"]


def test_score_preview_decomposition_formula():
    service = TaxonomyService(TaxonomyRepository(storage_path=None))
    service.create_or_update_rule("42.11", MODE_BOOST, 0.25, "Road works boost")

    decomp = service.compute_adjusted_priority(0.65, "42.11.20")
    assert decomp["base_model_score"] == 0.65
    assert decomp["taxonomy_adjustment"] == 0.25
    assert decomp["final_shadow_score"] == 0.90


def test_tie_safe_ranking_with_equal_probabilities():
    titles = [
        "Ремонт моста 1",
        "Ремонт моста 2",
        "Поставка шприцев 1",
        "Поставка шприцев 2",
    ]
    okpds = ["42.11", "42.11", "32.50", "32.50"]
    prices = [1000000.0, 1000000.0, 50000.0, 50000.0]
    y = [1, 1, 0, 0]

    model = ResearchPriorityModelV2().fit(titles, okpds, prices, y)
    pop = [
        {"procurement_id": 101, "auction_name": "Ремонт моста 1", "okpd_code": "42.11"},
        {"procurement_id": 102, "auction_name": "Ремонт моста 2", "okpd_code": "42.11"},
    ]
    scored = model.score_population(pop)
    assert len(scored) == 2
    assert scored[0].priority_percentile == scored[1].priority_percentile
    assert scored[0].priority_band == scored[1].priority_band


def test_superuser_proposal_generation_empty_when_no_clusters():
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)

    evidence_data = [
        {"procurement_id": 1, "okpd_code": "42.11", "research_hit": 1},
        {"procurement_id": 2, "okpd_code": "26.20", "research_hit": 0},
    ]
    proposals = service.generate_proposals_from_evidence(evidence_data)
    assert len(proposals) == 0


def test_superuser_proposal_approval_creates_active_rule():
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)

    evidence_data = [
        {"procurement_id": 1, "okpd_code": "43.33.10", "okpd_root": "43", "okpd_level2": "43.33", "research_hit": 1},
        {"procurement_id": 2, "okpd_code": "43.33.20", "okpd_root": "43", "okpd_level2": "43.33", "research_hit": 1},
    ]
    proposals = service.generate_proposals_from_evidence(evidence_data)
    assert len(proposals) >= 1

    rule = service.approve_proposal(proposals[0].proposal_id, actor="admin_user")
    assert rule is not None
    assert rule.is_active is True
    assert rule.created_by == "admin_user"


def test_taxonomy_service_audit_trail_pagination():
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)
    for i in range(15):
        service.create_or_update_rule(f"42.{i}", MODE_BOOST, 0.10, f"Rule {i}")
    logs = repo.get_audit_logs(limit=10)
    assert len(logs) == 10


def test_taxonomy_service_update_existing_rule_changes_weight():
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)
    rule = service.create_or_update_rule("42.11", MODE_BOOST, 0.20, "Old weight", rule_id="fixed_id")
    assert rule.adjustment_weight == 0.20
    updated = service.create_or_update_rule("42.11", MODE_BOOST, 0.35, "New weight", rule_id="fixed_id")
    assert updated.adjustment_weight == 0.35
    matched = service.find_matching_rule("42.11.20")
    assert matched.adjustment_weight == 0.35


def test_taxonomy_service_inactive_rules_ignored_in_matching():
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)
    rule = service.create_or_update_rule("42.11", MODE_BOOST, 0.20, "Active")
    rule.is_active = False
    repo.upsert_rule(rule)
    assert service.find_matching_rule("42.11.20") is None


def test_taxonomy_service_neutral_mode_zero_adjustment():
    service = TaxonomyService(TaxonomyRepository(storage_path=None))
    service.create_or_update_rule("41.20", MODE_NEUTRAL, 0.0, "Neutral")
    res = service.compute_adjusted_priority(0.50, "41.20.10")
    assert res["taxonomy_adjustment"] == 0.0
    assert res["final_shadow_score"] == 0.50


def test_taxonomy_service_unmatched_code_returns_neutral():
    service = TaxonomyService(TaxonomyRepository(storage_path=None))
    res = service.compute_adjusted_priority(0.60, "99.99.99")
    assert res["rule_mode"] == MODE_NEUTRAL
    assert res["taxonomy_adjustment"] == 0.0
    assert res["final_shadow_score"] == 0.60


def test_taxonomy_service_proposal_with_sparse_data_ignored():
    service = TaxonomyService(TaxonomyRepository(storage_path=None))
    evidence = [{"procurement_id": 1, "okpd_code": "88.88", "research_hit": 1}]
    props = service.generate_proposals_from_evidence(evidence)
    assert len(props) == 0


def test_taxonomy_service_rule_persistence_across_multiple_upserts():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = os.path.join(tmpdir, "tax.json")
        repo = TaxonomyRepository(storage_path=storage)
        service = TaxonomyService(repo)
        service.create_or_update_rule("42", MODE_BOOST, 0.10, "R1")
        service.create_or_update_rule("43", MODE_BOOST, 0.20, "R2")
        service.create_or_update_rule("26", MODE_DOWNWEIGHT, -0.20, "R3")

        repo_new = TaxonomyRepository(storage_path=storage)
        assert len(repo_new.get_all_rules()) == 3


def test_disambiguation_food_domain_suppression():
    sig = extract_domain_signals("Поставка продуктов питания: молоко, хлеб, масло сливочное", "10.51")
    assert sig["food_risk"] >= 0.8
    assert sig["construction_prior"] == 0.0


def test_disambiguation_furniture_domain_suppression():
    sig = extract_domain_signals("Поставка офисной мебели: столы письменные, стулья, шкафы для документов", "31.01")
    assert sig["furniture_risk"] >= 0.7
    assert sig["construction_prior"] == 0.0


def test_disambiguation_it_domain_suppression():
    sig = extract_domain_signals("Закупка серверов, коммутаторов и систем хранения данных для ЦОД", "26.20")
    assert sig["it_electronics_risk"] >= 0.7
    assert sig["construction_prior"] == 0.0


def test_text_baseline_empty_titles_raises_value_error():
    model = TitleTextBaselineV2()
    with pytest.raises(ValueError):
        model.fit([], [])


def test_text_baseline_length_mismatch_raises_value_error():
    model = TitleTextBaselineV2()
    with pytest.raises(ValueError):
        model.fit(["Title 1"], [1, 0])


def test_semantic_model_empty_titles_raises_value_error():
    model = TitleSemanticModelV2()
    with pytest.raises(ValueError):
        model.fit([], [], [])


def test_combined_v2_unfitted_raises_runtime_error():
    model = ResearchPriorityModelV2()
    with pytest.raises(RuntimeError):
        model.predict_proba(["Title 1"])


def test_combined_v2_empty_population_returns_empty_list():
    model = ResearchPriorityModelV2()
    model.is_fitted = True
    assert model.score_population([]) == []
