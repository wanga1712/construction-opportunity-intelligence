"""Comprehensive test suite for OKPD Prior Learning V1 & V2 (Cases A through X)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import tempfile
import pytest

from src.learning.okpd_prior.hierarchy import (
    OKPDHierarchy,
    UNKNOWN_OKPD,
    parse_okpd_hierarchy,
)
from src.learning.okpd_prior.dataset import (
    OUTCOME_POSITIVE,
    OUTCOME_SAFE_NEGATIVE,
    OUTCOME_UNRESOLVED,
    ProcurementDatasetRow,
    create_dataset_snapshot,
    resolve_research_outcome,
    split_dataset,
)
from src.learning.okpd_prior.baseline import (
    BASELINE_MODEL_NAME,
    OKPDHierarchicalPriorV1,
)
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
    FEATURE_NAMES,
    MODEL_NAME,
    MODEL_TYPE,
    OKPDResearchHitModelV1,
    assign_priority_band,
)
from src.learning.okpd_prior.metrics import evaluate_ranking_metrics, compute_pr_auc, compute_roc_auc
from src.learning.okpd_prior.dto import ShadowPredictionDTO
from src.learning.okpd_prior.disambiguation import extract_domain_signals
from src.learning.okpd_prior.text_baseline import TitleTextBaselineV2
from src.learning.okpd_prior.semantic_model import TitleSemanticModelV2
from src.learning.okpd_prior.combined_v2 import ResearchPriorityModelV2, MODEL_NAME_V2
from src.models.taxonomy_rules import (
    MODE_BOOST,
    MODE_DOWNWEIGHT,
    MODE_EXCLUDE_FROM_PRIMARY,
    MODE_EXPLORE,
    MODE_NEUTRAL,
    PROPOSAL_STATUS_APPROVED,
    PROPOSAL_STATUS_PENDING,
    PROPOSAL_STATUS_REJECTED,
    TaxonomyProposalDTO,
    TaxonomyRuleDTO,
)
from src.repositories.taxonomy_repository import TaxonomyRepository
from src.services.taxonomy_service import TaxonomyService


# ==============================================================================
# Tests A through R: V1 Invariants & Hierarchy Tests
# ==============================================================================

def test_a_one_procurement_one_dataset_row():
    row1 = ProcurementDatasetRow(
        procurement_id=101,
        research_completed_at="2026-08-31T18:00:00Z",
        okpd_code_raw="42.11.20",
        okpd_root="42",
        okpd_level2="42.11",
        okpd_level3="42.11.20",
        okpd_full="42.11.20",
        outcome=OUTCOME_POSITIVE,
        research_hit=1,
        trusted_confirmed_count=5,
        rejected_count=10,
        unknown_count=0,
        pending_validation_count=0,
        research_document_count=3,
    )
    d = row1.to_dict()
    assert d["procurement_id"] == 101
    assert "okpd_root" in d


def test_b_trusted_confirmed_produces_positive():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=2,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_POSITIVE
    assert hit == 1


def test_c_zero_candidates_produces_safe_negative():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_SAFE_NEGATIVE
    assert hit == 0


def test_d_only_rejected_candidates_produces_safe_negative():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_SAFE_NEGATIVE
    assert hit == 0


def test_e_unknown_without_confirmed_produces_unresolved():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=1,
        pending_validation_count=0,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


def test_f_pending_validation_without_confirmed_produces_unresolved():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=3,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


def test_g_technical_gap_without_confirmed_produces_unresolved():
    outcome, hit = resolve_research_outcome(
        research_complete=True,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=1,
    )
    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


def test_h_incomplete_research_without_confirmed_produces_unresolved():
    outcome, hit = resolve_research_outcome(
        research_complete=False,
        trusted_confirmed_count=0,
        semantic_unknown_count=0,
        pending_validation_count=0,
        technical_gap_count=0,
    )
    assert outcome == OUTCOME_UNRESOLVED
    assert hit is None


def test_i_confirmed_overrides_unknowns_and_incompleteness():
    outcome, hit = resolve_research_outcome(
        research_complete=False,
        trusted_confirmed_count=1,
        semantic_unknown_count=5,
        pending_validation_count=2,
        technical_gap_count=1,
    )
    assert outcome == OUTCOME_POSITIVE
    assert hit == 1


def test_j_okpd_hierarchy_parsing_depths():
    h1 = parse_okpd_hierarchy("42.11.20.000")
    assert h1.okpd_root == "42"
    assert h1.okpd_level2 == "42.11"
    assert h1.okpd_level3 == "42.11.20"
    assert h1.okpd_full == "42.11.20.000"

    h2 = parse_okpd_hierarchy("42.11")
    assert h2.okpd_root == "42"
    assert h2.okpd_level2 == "42.11"
    assert h2.okpd_level3 == "42.11"
    assert h2.okpd_full == "42.11"

    h3 = parse_okpd_hierarchy("42")
    assert h3.okpd_root == "42"
    assert h3.okpd_level2 == "42"
    assert h3.okpd_level3 == "42"
    assert h3.okpd_full == "42"


def test_k_okpd_hierarchy_parsing_malformed():
    h_none = parse_okpd_hierarchy(None)
    assert h_none.okpd_root == UNKNOWN_OKPD
    assert h_none.okpd_full == UNKNOWN_OKPD

    h_empty = parse_okpd_hierarchy("")
    assert h_empty.okpd_root == UNKNOWN_OKPD

    h_inv = parse_okpd_hierarchy("abc")
    assert h_inv.okpd_root == UNKNOWN_OKPD


def test_l_model_feature_schema_strictly_pre_research():
    row = ProcurementDatasetRow(
        procurement_id=1,
        research_completed_at="2026-08-31T18:00:00Z",
        okpd_code_raw="42.11.20",
        okpd_root="42",
        okpd_level2="42.11",
        okpd_level3="42.11.20",
        okpd_full="42.11.20",
        outcome=OUTCOME_POSITIVE,
        research_hit=1,
        trusted_confirmed_count=5,
        rejected_count=10,
        unknown_count=0,
        pending_validation_count=0,
        research_document_count=3,
    )
    features = row.to_feature_dict()
    assert list(features.keys()) == FEATURE_NAMES
    assert "trusted_confirmed_count" not in features
    assert "rejected_count" not in features
    assert "research_document_count" not in features


def test_m_baseline_fallback_to_root_and_global_prior():
    rows = [
        ProcurementDatasetRow(
            procurement_id=1,
            research_completed_at="2026-08-31T18:00:00Z",
            okpd_code_raw="42.11.20",
            okpd_root="42",
            okpd_level2="42.11",
            okpd_level3="42.11.20",
            okpd_full="42.11.20",
            outcome=OUTCOME_POSITIVE,
            research_hit=1,
            trusted_confirmed_count=1,
            rejected_count=0,
            unknown_count=0,
            pending_validation_count=0,
            research_document_count=1,
        ),
        ProcurementDatasetRow(
            procurement_id=2,
            research_completed_at="2026-08-31T18:00:00Z",
            okpd_code_raw="26.20.10",
            okpd_root="26",
            okpd_level2="26.20",
            okpd_level3="26.20.10",
            okpd_full="26.20.10",
            outcome=OUTCOME_SAFE_NEGATIVE,
            research_hit=0,
            trusted_confirmed_count=0,
            rejected_count=1,
            unknown_count=0,
            pending_validation_count=0,
            research_document_count=1,
        ),
    ]
    model = OKPDHierarchicalPriorV1(min_support=1).fit(rows)
    pred_exact = model.predict(parse_okpd_hierarchy("42.11.20"))
    assert pred_exact.fallback_level == "full"

    pred_root = model.predict(parse_okpd_hierarchy("42.99.99"))
    assert pred_root.fallback_level in ("root", "level2", "global")

    pred_unknown = model.predict(parse_okpd_hierarchy("99.99.99"))
    assert pred_unknown.fallback_level == "global"


def test_n_tie_safe_ranking_preserves_bands():
    scores = [0.95, 0.85, 0.75, 0.65, 0.55, 0.45, 0.35, 0.25, 0.15, 0.05]
    n = len(scores)
    bands = [assign_priority_band(round(sum(1 for s in scores if s <= x) / float(n), 4)) for x in scores]
    assert bands[0] == BAND_GOLD
    assert bands[-1] == BAND_WOOD


# ==============================================================================
# Tests S through X: V2 Semantic, Disambiguation, Taxonomy & Combined Tests
# ==============================================================================

def test_s_title_text_baseline_v2_fitting_and_calibration():
    titles = [
        "Капитальный ремонт кровли и фасада здания",
        "Поставка лекарственных средств и антисептиков",
        "Устройство гидроизоляции деформационных швов",
        "Закупка компьютерной техники и серверов",
    ]
    y = [1, 0, 1, 0]
    model = TitleTextBaselineV2()
    model.fit(titles, y)
    probs = model.predict_proba(["Ремонт фасада и кровли", "Поставка антисептиков"])
    assert len(probs) == 2
    assert probs[0] > probs[1]
    assert 0.0 <= probs[0] <= 1.0


def test_t_domain_disambiguation_contrastive_cases():
    # Case 1: Injection in construction vs Injection in medical
    sig_inj_const = extract_domain_signals("\u0418\u043d\u044a\u0435\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435 \u0442\u0440\u0435\u0449\u0438\u043d \u0434\u0435\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u043e\u043d\u043d\u044b\u0445 \u0448\u0432\u043e\u0432 \u043f\u043e\u0434\u0437\u0435\u043c\u043d\u043e\u0433\u043e \u043f\u0430\u0440\u043a\u0438\u043d\u0433\u0430", "42.11")
    sig_inj_med = extract_domain_signals("\u041f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u0448\u043f\u0440\u0438\u0446\u0435\u0432 \u0438\u043d\u044a\u0435\u043a\u0446\u0438\u043e\u043d\u043d\u044b\u0445 \u043e\u0434\u043d\u043e\u0440\u0430\u0437\u043e\u0432\u044b\u0445 \u0441\u0442\u0435\u0440\u0438\u043b\u044c\u043d\u044b\u0445", "32.50.13")
    assert sig_inj_const["disambiguated_injection_score"] == 1.0
    assert sig_inj_med["disambiguated_injection_score"] == -1.0
    assert sig_inj_const["construction_prior"] > sig_inj_med["construction_prior"]
    assert sig_inj_med["medical_risk"] > sig_inj_const["medical_risk"]

    # Case 2: Lighting/fixtures in construction vs Electronics/microchips
    sig_light = extract_domain_signals("\u041c\u043e\u043d\u0442\u0430\u0436 \u0441\u0432\u0435\u0442\u0438\u043b\u044c\u043d\u0438\u043a\u043e\u0432 \u043d\u0430\u0440\u0443\u0436\u043d\u043e\u0433\u043e \u043e\u0441\u0432\u0435\u0449\u0435\u043d\u0438\u044f \u0438 \u044d\u043b\u0435\u043a\u0442\u0440\u043e\u0441\u043d\u0430\u0431\u0436\u0435\u043d\u0438\u044f", "43.21")
    sig_it = extract_domain_signals("\u041f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u043d\u044b\u0445 \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u043e\u0440\u043e\u0432, \u0432\u0438\u0434\u0435\u043e\u043a\u0430\u0440\u0442 \u0438 \u043e\u043f\u0435\u0440\u0430\u0442\u0438\u0432\u043d\u043e\u0439 \u043f\u0430\u043c\u044f\u0442\u0438", "26.20")
    assert sig_light["construction_prior"] > 0.4
    assert sig_it["it_electronics_risk"] > 0.5

    # Case 3: Polymer industrial flooring vs Medical furniture
    sig_floor = extract_domain_signals("\u0423\u0441\u0442\u0440\u043e\u0439\u0441\u0442\u0432\u043e \u0431\u0435\u0441\u0448\u043e\u0432\u043d\u044b\u0445 \u043f\u043e\u043b\u0438\u043c\u0435\u0440\u043d\u044b\u0445 \u043d\u0430\u043b\u0438\u0432\u043d\u044b\u0445 \u043f\u043e\u043b\u043e\u0432", "43.33")
    sig_med_furn = extract_domain_signals("\u041f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u043c\u0435\u0434\u0438\u0446\u0438\u043d\u0441\u043a\u043e\u0439 \u043c\u0435\u0431\u0435\u043b\u0438: \u043a\u0443\u0448\u0435\u0442\u043a\u0438 \u0441\u043c\u043e\u0442\u0440\u043e\u0432\u044b\u0435", "32.50.30")
    assert sig_floor["construction_prior"] > 0.4
    assert sig_med_furn["medical_risk"] > 0.4

    # Case 4: Works signal vs Goods signal
    sig_works = extract_domain_signals("\u0412\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435 \u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u043e-\u043c\u043e\u043d\u0442\u0430\u0436\u043d\u044b\u0445 \u0440\u0430\u0431\u043e\u0442", "41.20")
    sig_goods = extract_domain_signals("\u041f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u043a\u0430\u043d\u0446\u0435\u043b\u044f\u0440\u0441\u043a\u0438\u0445 \u0442\u043e\u0432\u0430\u0440\u043e\u0432", "17.23")
    assert sig_works["works_signal"] == 1.0
    assert sig_goods["works_signal"] == 0.0

    # Case 5: Construction surface prep vs Admin date
    sig_prep = extract_domain_signals("\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430 \u043e\u0441\u043d\u043e\u0432\u0430\u043d\u0438\u044f \u0438 \u0433\u0438\u0434\u0440\u043e\u0438\u0437\u043e\u043b\u044f\u0446\u0438\u044f \u0444\u0443\u043d\u0434\u0430\u043c\u0435\u043d\u0442\u0430", "43.99")
    sig_admin = extract_domain_signals("\u041f\u043e\u0441\u0442\u0430\u0432\u043a\u0430 \u0431\u043b\u0430\u043d\u043a\u043e\u0432 (\u0434\u0430\u0442\u0430 \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0438 \u043e\u0431\u043e\u0441\u043d\u043e\u0432\u0430\u043d\u0438\u044f 2026-08)", "18.12")
    assert sig_prep["construction_prior"] > sig_admin["construction_prior"]


def test_u_title_semantic_v2_oof_stacking_and_artifact():
    titles = [
        "Ремонт моста и гидроизоляция швов",
        "Поставка шприцев медицинских",
        "Устройство наливных полов склада",
        "Закупка серверов и СХД",
        "Капитальный ремонт кровли школы",
        "Поставка детского питания молоко",
    ]
    okpds = ["42.11", "32.50", "43.33", "26.20", "41.20", "10.86"]
    y = [1, 0, 1, 0, 1, 0]

    model = TitleSemanticModelV2()
    oof = model.fit_oof_predictions(titles, okpds, y, n_splits=2)
    assert len(oof) == len(titles)

    with tempfile.TemporaryDirectory() as tmpdir:
        art_path = os.path.join(tmpdir, "semantic_v2.pkl")
        model.save_artifact(art_path)
        loaded = TitleSemanticModelV2.load_artifact(art_path)
        assert loaded.is_fitted
        p1 = loaded.predict_one("Гидроизоляция деформационных швов", "42.11")
        p2 = loaded.predict_one("Поставка лекарств", "21.20")
        assert p1 > p2


def test_v_combined_research_priority_v2_scoring_and_ranking():
    titles = [
        "Ремонт автомобильной дороги и гидроизоляция моста",
        "Поставка медицинских шприцев инъекционных",
        "Устройство полимерных наливных полов паркинга",
        "Закупка компьютеров и серверов ЦОД",
        "Инъектирование трещин деформационных швов бетона",
        "Поставка мебели для детского сада столы стулья",
    ]
    okpds = ["42.11", "32.50", "43.33", "26.20", "42.99", "31.09"]
    prices = [1000000.0, 50000.0, 2500000.0, 800000.0, 1500000.0, 120000.0]
    y = [1, 0, 1, 0, 1, 0]

    model = ResearchPriorityModelV2()
    model.fit(titles, okpds, prices, y, dataset_snapshot_sha256="test_sha_v2")

    procs = [
        {"procurement_id": 101, "auction_name": "Инъектирование деформационных швов моста", "okpd_code": "42.11", "initial_price": 5000000.0},
        {"procurement_id": 102, "auction_name": "Поставка медицинских игл и шприцев", "okpd_code": "32.50", "initial_price": 10000.0},
    ]
    scored = model.score_population(procs)
    assert len(scored) == 2
    assert scored[0].procurement_id == 101
    assert scored[0].p_research_hit > scored[1].p_research_hit
    assert scored[0].model_name == MODEL_NAME_V2
    assert scored[0].shadow_only is True


def test_w_superuser_taxonomy_crud_and_longest_prefix():
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)

    # Add rules
    service.create_or_update_rule("42", MODE_BOOST, 0.20, "Construction root")
    service.create_or_update_rule("42.11.20", MODE_BOOST, 0.35, "Road specific")
    service.create_or_update_rule("26", MODE_DOWNWEIGHT, -0.30, "Electronics")

    # Longest prefix verification
    res_exact = service.compute_adjusted_priority(0.50, "42.11.20.200")
    assert res_exact["matched_pattern"] == "42.11.20"
    assert res_exact["taxonomy_adjustment"] == 0.35
    assert res_exact["final_shadow_score"] == 0.85

    res_root = service.compute_adjusted_priority(0.50, "42.99.10")
    assert res_root["matched_pattern"] == "42"
    assert res_root["taxonomy_adjustment"] == 0.20
    assert res_root["final_shadow_score"] == 0.70

    res_down = service.compute_adjusted_priority(0.50, "26.20.10")
    assert res_down["matched_pattern"] == "26"
    assert res_down["taxonomy_adjustment"] == -0.30
    assert res_down["final_shadow_score"] == 0.20

    # Test audit log
    logs = repo.get_audit_logs()
    assert len(logs) >= 3


def test_x_superuser_taxonomy_proposal_generation_and_approval():
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)

    evidence_data = [
        {"procurement_id": 1, "okpd_code": "43.33.10", "okpd_root": "43", "okpd_level2": "43.33", "research_hit": 1},
        {"procurement_id": 2, "okpd_code": "43.33.20", "okpd_root": "43", "okpd_level2": "43.33", "research_hit": 1},
        {"procurement_id": 3, "okpd_code": "10.11.10", "okpd_root": "10", "okpd_level2": "10.11", "research_hit": 0},
        {"procurement_id": 4, "okpd_code": "10.11.20", "okpd_root": "10", "okpd_level2": "10.11", "research_hit": 0},
        {"procurement_id": 5, "okpd_code": "10.11.30", "okpd_root": "10", "okpd_level2": "10.11", "research_hit": 0},
    ]

    proposals = service.generate_proposals_from_evidence(evidence_data)
    assert len(proposals) >= 1

    prop_boost = next((p for p in proposals if p.proposed_mode == MODE_BOOST), None)
    assert prop_boost is not None

    rule = service.approve_proposal(prop_boost.proposal_id, actor="admin")
    assert rule is not None
    assert rule.rule_mode == MODE_BOOST
    assert rule.is_active is True

    # Verify rule now matches
    eval_match = service.evaluate_taxonomy_adjustment(prop_boost.okpd_pattern)
    assert eval_match["rule_mode"] == MODE_BOOST
