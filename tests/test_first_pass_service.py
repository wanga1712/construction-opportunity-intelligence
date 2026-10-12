"""Unit tests for First Pass service, pure resolvers, multiplicity handling, and invariants."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from src.services.first_pass.resolver import (
    calculate_deadline_metrics,
    calculate_priority_score,
    normalize_medal_name,
    normalize_to_100,
    resolve_canonical_preliminary_medal,
    resolve_download_decision,
    resolve_object_family,
    select_best_eligible_category_opportunity,
)
from src.services.first_pass.service import FirstPassService
from src.services.first_pass.types import FirstPassResult


class MockDB:
    def __init__(self, query_responses=None):
        self.query_responses = query_responses or {}

    def execute_query(self, sql, params=None):
        for k, v in self.query_responses.items():
            if k in sql:
                return v
        return []


def test_normalize_to_100():
    assert normalize_to_100(0.85) == (85.0, 0.85)
    assert normalize_to_100(85.0) == (85.0, 85.0)
    assert normalize_to_100(0.0) == (0.0, 0.0)
    assert normalize_to_100(None) == (0.0, None)
    assert normalize_to_100("0.95") == (95.0, 0.95)


def test_select_best_eligible_category_opportunity_multiplicity():
    # Multiple opportunities for 1 procurement
    opps = [
        # 1. Bronze (active)
        {"id": 1, "candidate_medal": "BRONZE", "candidate_score": 40.0, "commercial_category_code": "drainage", "commercial_state": "CONFIRMED"},
        # 2. Gold (rejected/excluded -> must be skipped)
        {"id": 2, "candidate_medal": "GOLD", "candidate_score": 90.0, "commercial_category_code": "lighting", "commercial_state": "REJECTED"},
        # 3. Silver (active, score 65)
        {"id": 3, "candidate_medal": "SILVER", "candidate_score": 65.0, "commercial_category_code": "flooring", "commercial_state": "CONFIRMED"},
        # 4. Silver (active, score 75 -> must win over Silver 65)
        {"id": 4, "candidate_medal": "SILVER", "candidate_score": 75.0, "commercial_category_code": "waterproofing", "commercial_state": "CONFIRMED"},
    ]

    best, total = select_best_eligible_category_opportunity(opps)
    assert total == 4
    assert best is not None
    assert best["id"] == 4
    assert best["commercial_category_code"] == "waterproofing"
    assert best["candidate_medal"] == "SILVER"


def test_resolve_object_family():
    # Explicit taxonomy takes precedence
    assert resolve_object_family(scope_type="DIRECT_GOODS", sector="SOCIAL", object_type="SCHOOL") == "SOCIAL"
    assert resolve_object_family(object_type="Строительство детского сада") == "SOCIAL"
    assert resolve_object_family(object_type="Реконструкция поликлиники") == "SOCIAL"
    
    # Commercial / Residential / Industrial
    assert resolve_object_family(sector="COMMERCIAL") == "COMMERCIAL"
    assert resolve_object_family(object_type="Строительство жилого дома") == "COMMERCIAL"
    assert resolve_object_family(object_type="Капитальный ремонт офиса") == "COMMERCIAL"
    assert resolve_object_family(object_type="ROAD") == "COMMERCIAL"

    # Direct Goods scope without social/commercial taxonomy
    assert resolve_object_family(scope_type="DIRECT_GOODS") == "DIRECT_SUPPLY"

    # Other
    assert resolve_object_family(sector="OTHER", object_type="OTHER_OBJECT") == "OTHER"


def test_bare_okpd_prior_never_produces_medal():
    """MEDAL SEMANTICS V2: a bare OKPD prior can never create a medal.

    OKPD priors may only nominate a candidate canonical category (routing /
    download priority). Prior weight no longer carries medal strength.
    """
    for weight, code in (
        (80.0, "computers"),
        (70.0, "lighting"),
        (50.0, "flooring"),
        (35.0, "curbstone"),
    ):
        medal, score, _, src, cat, _, _, _ = resolve_canonical_preliminary_medal(
            okpd_target_classification="TARGET",
            matched_priors=[{"commercial_category_code": code, "prior_weight": weight}],
        )
        assert medal == "UNASSESSED", (code, weight)
        assert score == 0.0
        assert src == "UNASSESSED"
        assert cat is None


def test_okpd_prior_nominates_category_then_semantics_decide():
    """The prior nominates the category; metadata semantics supply the medal."""
    medal, score, _, src, cat, _, _, _ = resolve_canonical_preliminary_medal(
        okpd_target_classification="TARGET",
        matched_priors=[{"commercial_category_code": "computers", "prior_weight": 80.0}],
        title="Поставка ноутбуков, серверов и мониторов",
    )
    assert medal == "GOLD"
    assert score == 70.0
    assert src == "METADATA_CATEGORY_SEMANTIC"
    assert cat == "computers"


def test_prior_with_irrelevant_title_is_not_gold():
    """Regression (CRM_ID=46550): 26.20 prior alone must not yield GOLD."""
    medal, _, _, src, _, _, _, _ = resolve_canonical_preliminary_medal(
        okpd_target_classification="TARGET",
        matched_priors=[{"commercial_category_code": "computers", "prior_weight": 80.0}],
        title="Поставка элементов замены типовых устройств ввода и вывода (картриджи для принтеров)",
        okpd_code="26.20.40.120",
    )
    assert medal != "GOLD"
    assert src != "CATEGORY_OKPD_PRIOR"


def test_no_double_counting_for_prior_weight():
    """A real prior nominates the category and adds no relevance bonus.

    MEDAL SEMANTICS V2: prior weight never upgrades a medal (only semantics do),
    and relevance_bonus stays 0 without an independent commercial opportunity.
    """
    mock_db = MockDB(query_responses={
        "crm_procurement_category_opportunities": [],
        "crm_category_okpd_priors": [
            {"commercial_category_code": "computers", "okpd_pattern": "26.20", "match_type": "PREFIX", "prior_weight": 80.0, "active": True}
        ]
    })
    service = FirstPassService(crm_db=mock_db)
    proc = {
        "id": 201,
        "contract_number": "32616216999",
        "title": "Поставка серверов",
        "okpd_code": "26.20.14",
        "end_date": "2026-09-25 10:00:00",  # 4 days away
    }
    now = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)
    res = service.evaluate_procurement(proc, now=now)

    # A single weak metadata signal ("сервер") = BRONZE, never GOLD from weight.
    assert res.canonical_preliminary_medal == "BRONZE"
    assert res.canonical_preliminary_source == "METADATA_CATEGORY_SEMANTIC"
    assert res.category == "computers"
    assert res.medal_base == 30
    assert res.urgency_bonus == 10  # 4 days is in (3..7] band -> +10
    # Strict check: relevance_bonus MUST BE 0 (no independent commercial candidate opportunity)
    assert res.relevance_bonus == 0
    # Priority score = 30 + 10 + 0 = 40
    assert res.priority_score == 40


def test_resolve_download_decision():
    # Out of target -> Skip
    assert resolve_download_decision("OUT_OF_TARGET", "GOLD", 5) == "DOWNLOAD_SKIP"

    # Zero docs -> No links
    assert resolve_download_decision("TARGET", "GOLD", 0) == "NO_LINKS"

    # Relevant Gold/Silver/Bronze -> Required
    assert resolve_download_decision("TARGET", "GOLD", 3) == "DOWNLOAD_REQUIRED"
    assert resolve_download_decision("TARGET", "SILVER", 3) == "DOWNLOAD_REQUIRED"
    assert resolve_download_decision("TARGET", "BRONZE", 3) == "DOWNLOAD_REQUIRED"

    # Wood standard -> Defer
    assert resolve_download_decision("TARGET", "WOOD", 3) == "DOWNLOAD_DEFER"

    # Unassessed -> Defer
    assert resolve_download_decision("TARGET", "UNASSESSED", 3) == "DOWNLOAD_DEFER"


def test_deadline_metrics_and_urgency():
    now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)

    # <= 1 day
    t_1d = now + timedelta(hours=18)
    bonus, days = calculate_deadline_metrics(t_1d, now=now)
    assert bonus == 20
    assert 0 < days <= 1.0

    # <= 3 days
    t_3d = now + timedelta(days=2, hours=12)
    bonus, days = calculate_deadline_metrics(t_3d, now=now)
    assert bonus == 15

    # Expired
    t_past = now - timedelta(days=1)
    bonus, days = calculate_deadline_metrics(t_past, now=now)
    assert bonus == 0
    assert days < 0


def test_priority_score_formula_and_invariants():
    now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    t_urgent = now + timedelta(hours=12)  # +20
    t_far = now + timedelta(days=30)     # +0
    t_expired = now - timedelta(days=2)  # expired -> 0

    # Gold Base = 70. Urgent with proven relevance = 70 + 20 + 10 = 100
    score, base, urg, rel, days = calculate_priority_score("GOLD", t_urgent, is_explicit_target_profile=True, now=now)
    assert score == 100
    assert base == 70
    assert urg == 20
    assert rel == 10

    # Urgent Gold without proven relevance = 70 + 20 + 0 = 90
    score_no_rel, _, _, rel_0, _ = calculate_priority_score("GOLD", t_urgent, is_explicit_target_profile=False, now=now)
    assert score_no_rel == 90
    assert rel_0 == 0

    # Non-urgent standard Gold = 70 + 0 + 0 = 70
    score_gold_far, _, _, _, _ = calculate_priority_score("GOLD", t_far, is_explicit_target_profile=False, now=now)
    assert score_gold_far == 70

    # Expired active procurement -> score = 0
    score_exp, _, _, _, days_exp = calculate_priority_score("GOLD", t_expired, is_explicit_target_profile=True, now=now)
    assert score_exp == 0
    assert days_exp < 0

    # Silver Base = 50. Urgent proven Silver = 50 + 20 + 10 = 80
    score_silver_urgent, _, _, _, _ = calculate_priority_score("SILVER", t_urgent, is_explicit_target_profile=True, now=now)
    assert score_silver_urgent == 80

    # INVARIANT 1: Urgent proven Silver (80) can beat non-urgent standard Gold (70)
    assert score_silver_urgent > score_gold_far

    # Wood Base = 10. Max possible Wood = 10 + 20 + 10 = 40
    score_wood_max, _, _, _, _ = calculate_priority_score("WOOD", t_urgent, is_explicit_target_profile=True, now=now)
    assert score_wood_max == 40

    # INVARIANT 2: Wood MAX (40) can NEVER leapfrog base Gold (70)
    assert score_wood_max < score_gold_far


def test_first_pass_service_batch_multiplicity():
    mock_db = MockDB(query_responses={
        "crm_procurement_category_opportunities": [
            {
                "id": 1001,
                "procurement_id": 101,
                "commercial_category_code": "drainage",
                "candidate_medal": "BRONZE",
                "candidate_score": 40.0,
                "commercial_state": "CONFIRMED",
                "opportunity_track": "DIRECT_SUPPLY",
            },
            {
                "id": 1002,
                "procurement_id": 101,
                "commercial_category_code": "lighting",
                "candidate_medal": "GOLD",
                "candidate_score": 88.0,
                "commercial_state": "CONFIRMED",
                "opportunity_track": "DIRECT_SUPPLY",
            }
        ],
        "crm_category_okpd_priors": [
            {"commercial_category_code": "lighting", "okpd_pattern": "27.40", "match_type": "PREFIX", "prior_weight": 70.0, "active": True}
        ]
    })

    service = FirstPassService(crm_db=mock_db)
    procs = [
        {"id": 101, "contract_number": "32616216109", "title": "Поставка светильников", "okpd_code": "27.40.10", "end_date": "2026-09-22 10:00:00"}
    ]

    now = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)
    batch_res = service.evaluate_batch(procs, now=now)

    assert 101 in batch_res
    res = batch_res[101]
    # Candidate medals identify the category only; they no longer carry strength.
    assert res.category_opportunity_count == 2
    assert res.selected_opportunity_id == 1002
    assert res.canonical_preliminary_medal == "BRONZE"
    assert res.canonical_preliminary_source == "METADATA_CATEGORY_SEMANTIC"
    assert res.canonical_preliminary_score == 30.0
    assert res.category == "lighting"
    assert res.object_family == "DIRECT_SUPPLY"
    assert res.urgency_bonus == 20
    assert res.relevance_bonus == 0
    assert res.priority_score == 50
