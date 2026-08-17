"""CRM-V3-OKPD-PRODUCT-BRANCH-AND-AWARDED-DIRECT-SUPPLY-INVARIANTS-1."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from src.domain.commercial_opportunity_lifecycle import (
    CommercialOpportunityState,
    SourceLifecycleEvent,
)
from src.domain.commercial_taxonomy import COMMERCIAL_KEEP_CODES
from src.services.commercial_routing_v3.canonical_card import proposed_routing_priority
from src.services.commercial_routing_v3.manager_object_ranking import (
    ManagerActionability,
    WorkbenchCommercialState,
    build_manager_object,
)
from src.services.commercial_routing_v3.model_input import model_input_as_prompt_procurement
from src.services.commercial_routing_v3.normalizer import normalize_v3_output
from src.services.commercial_routing_v3.object_mode_routing import enrich_object_mode_routing
from src.services.commercial_routing_v3.okpd_priors import match_okpd_priors, prefix_matches
from src.services.commercial_routing_v3.okpd_product_branch import (
    MATCH_DESCENDANT,
    OKPD_PRODUCT_BRANCH_PRIOR,
    ancestry_codes_from_hierarchy,
    broad_okpd_is_direct_product_proof,
    match_expert_product_branches,
    refine_subcategory,
    resolve_direct_goods_product_family,
)
from src.services.commercial_routing_v3.opportunity_lifecycle_sync import (
    _compute_decision,
    compute_opportunity_lifecycle_updates,
)
from src.services.commercial_routing_v3.post_award_execution_timing import compute_execution_clock
from src.services.commercial_routing_v3.research_queue_lifecycle import (
    document_research_required_for_commercial_entry,
    dry_run_research_admission,
)

ALLOWED = set(COMMERCIAL_KEEP_CODES)

COMPUTERS_BRANCH = {
    "commercial_category_code": "computers",
    "okpd_pattern": "26.20",
    "match_type": "PREFIX",
    "prior_weight": 80,
    "active": True,
    "prior_kind": "COMMERCIAL_PRODUCT_PRIOR",
    "provenance": "routing_v3_seed",
}

CONTEXTUAL_42 = {
    "commercial_category_code": "drainage_water_management",
    "okpd_pattern": "42.11",
    "match_type": "PREFIX",
    "prior_weight": 25,
    "active": True,
    "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR",
    "signal_role": "CONTEXTUAL",
}

CONTEXTUAL_71 = {
    "commercial_category_code": "lighting",
    "okpd_pattern": "71.12",
    "match_type": "PREFIX",
    "prior_weight": 20,
    "active": True,
    "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR",
    "signal_role": "CONTEXTUAL",
}

LIGHTING_PRODUCT = {
    "commercial_category_code": "lighting",
    "okpd_pattern": "27.40",
    "match_type": "PREFIX",
    "prior_weight": 70,
    "active": True,
    "prior_kind": "COMMERCIAL_PRODUCT_PRIOR",
}

COMPUTER_ANCESTRY = [
    {"code": "26.20.11.110", "name": "Ноутбуки", "depth": 0},
    {"code": "26.20.11", "name": "Портативные компьютеры", "depth": 1},
    {"code": "26.20", "name": "Компьютеры и периферийное оборудование", "depth": 2},
    {"code": "26", "name": "Компьютерная, электронная и оптическая техника", "depth": 3},
]


def test_okpd_canonical_exact_code_uses_sub_code_dot_boundary() -> None:
    assert prefix_matches("26.20.11.110", "26.20", "PREFIX")
    assert not prefix_matches("26.21.00.000", "26.20", "PREFIX")
    assert prefix_matches("26.20.11.110", "26.20.11.110", "EXACT")
    assert not prefix_matches("26.20.11.110", "26.20.11.111", "EXACT")


def test_okpd_parent_id_hierarchy_and_descendant_branch() -> None:
    ancestry = ancestry_codes_from_hierarchy(COMPUTER_ANCESTRY)
    assert ancestry[0] == "26.20.11.110"
    assert "26.20" in ancestry
    hits = match_expert_product_branches(
        "26.20.11.110", [COMPUTERS_BRANCH], ancestry_codes=ancestry
    )
    assert hits
    assert hits[0]["rule_type"] == OKPD_PRODUCT_BRANCH_PRIOR
    assert hits[0]["match_type"] == MATCH_DESCENDANT
    assert hits[0]["commercial_category_code"] == "computers"
    assert hits[0]["evidence_role"] == "COMMERCIAL_PRODUCT_PRIOR"


def test_expert_product_branch_only_not_every_parent() -> None:
    assert match_expert_product_branches("42.11.10.000", [CONTEXTUAL_42]) == []
    other_ancestry = ["26.21.00.000", "26.21", "26"]
    assert (
        match_expert_product_branches(
            "26.21.00.000", [COMPUTERS_BRANCH], ancestry_codes=other_ancestry
        )
        == []
    )


def test_computers_product_branch_direct_goods_open() -> None:
    resolved = resolve_direct_goods_product_family(
        procurement_form="DIRECT_GOODS_PURCHASE",
        exact_okpd="26.20.11.110",
        priors=[COMPUTERS_BRANCH, CONTEXTUAL_42],
        ancestry_codes=ancestry_codes_from_hierarchy(COMPUTER_ANCESTRY),
        title="Поставка ноутбуков для школы",
        allowed_subcategories={"laptops", "desktop_computers"},
        subcategory_lexicon={"laptops": ["ноутбук"], "desktop_computers": ["настольный компьютер"]},
    )
    assert resolved["commercial_category_code"] == "computers"
    assert resolved["opportunity_track"] == "DIRECT_SUPPLY"
    assert resolved["evidence_role"] == "COMMERCIAL_PRODUCT_PRIOR"
    assert resolved["DIRECT_GOODS_ADJACENCY_EXPANSION_COUNT"] == 0
    assert resolved["commercial_subcategory_code"] == "laptops"
    obj = build_manager_object(
        {
            "procurement_id": 1,
            "lifecycle": "OPEN",
            "routing_mode": "DIRECT_OR_OTHER",
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "hypotheses": [
                {
                    "category": "computers",
                    "track": "DIRECT_SUPPLY",
                    "candidate_medal": "SILVER",
                    "final_score": 55,
                    "candidate_score": 55,
                }
            ],
        }
    )
    assert obj["workbench_status"] == WorkbenchCommercialState.PREQUALIFIED_ACTIVE.value


def test_direct_goods_subcategory_optional_null() -> None:
    resolved = resolve_direct_goods_product_family(
        procurement_form="DIRECT_GOODS_PURCHASE",
        exact_okpd="26.20.11.110",
        priors=[COMPUTERS_BRANCH],
        ancestry_codes=ancestry_codes_from_hierarchy(COMPUTER_ANCESTRY),
        title="Поставка вычислительной техники",
        allowed_subcategories={"laptops", "desktop_computers"},
        subcategory_lexicon={"laptops": ["ноутбук"]},
    )
    assert resolved["commercial_category_code"] == "computers"
    assert resolved["commercial_subcategory_code"] is None
    assert refine_subcategory(
        category="computers", title="unknown goods", allowed_subcategories={"laptops"}
    ) is None


def test_direct_goods_no_adjacency() -> None:
    resolved = resolve_direct_goods_product_family(
        procurement_form="DIRECT_GOODS_PURCHASE",
        exact_okpd="26.20.11.110",
        priors=[COMPUTERS_BRANCH, CONTEXTUAL_42],
        ancestry_codes=ancestry_codes_from_hierarchy(COMPUTER_ANCESTRY),
        title="Поставка компьютеров",
    )
    assert resolved["adjacent_categories"] == []
    assert resolved["DIRECT_GOODS_ADJACENCY_EXPANSION_COUNT"] == 0


def test_child_outside_computers_branch_does_not_inherit() -> None:
    resolved = resolve_direct_goods_product_family(
        procurement_form="DIRECT_GOODS_PURCHASE",
        exact_okpd="26.21.00.000",
        priors=[COMPUTERS_BRANCH],
        ancestry_codes=["26.21.00.000", "26.21", "26"],
        title="Поставка оптического оборудования",
    )
    assert resolved["commercial_category_code"] is None


def test_broad_42_and_71_not_direct_product_proof() -> None:
    assert broad_okpd_is_direct_product_proof("42.11.10.130", [CONTEXTUAL_42, COMPUTERS_BRANCH]) is False
    assert broad_okpd_is_direct_product_proof("71.12.11", [CONTEXTUAL_71, COMPUTERS_BRANCH]) is False
    hits = match_okpd_priors("42.11.10.130", [COMPUTERS_BRANCH, CONTEXTUAL_42])
    assert all(h.get("commercial_category_code") != "computers" for h in hits)


def test_commercial_product_vs_contextual_prior() -> None:
    product = resolve_direct_goods_product_family(
        procurement_form="DIRECT_GOODS_PURCHASE",
        exact_okpd="26.20.11.110",
        priors=[COMPUTERS_BRANCH],
        ancestry_codes=ancestry_codes_from_hierarchy(COMPUTER_ANCESTRY),
    )
    assert product["evidence_role"] == "COMMERCIAL_PRODUCT_PRIOR"
    assert match_expert_product_branches("42.11", [CONTEXTUAL_42]) == []


def test_awarded_object_mislabelled_direct_supply_stays_followup() -> None:
    """AWARDED construction must not close as DIRECT_SUPPLY_CLOSED from a dirty track."""
    fu = _compute_decision(
        track="DIRECT_SUPPLY",
        source_event=SourceLifecycleEvent.AWARDED,
        procurement_form="CONSTRUCTION_WORKS",
    )
    assert fu.commercial_state == CommercialOpportunityState.FOLLOW_UP_AWARDED
    assert fu.reason == "FOLLOWUP_AWARDED"
    closed = _compute_decision(
        track="DIRECT_SUPPLY",
        source_event=SourceLifecycleEvent.AWARDED,
        procurement_form="DIRECT_GOODS_PURCHASE",
    )
    assert closed.commercial_state == CommercialOpportunityState.CLOSED
    assert closed.reason == "DIRECT_SUPPLY_CLOSED"
    updated, audit = compute_opportunity_lifecycle_updates(
        source_procurements=[
            {
                "procurement_id": 20228,
                "source_table": "reestr_contract_44_fz_awarded",
                "contract_number": "CN-20228",
                "crm_stage": "razygranye",
                "award_status": "awarded",
                "auction_name": (
                    'Капитальный ремонт здания МКОУ "Средняя общеобразовательная школа №6"'
                ),
                "okpd_code": "41.20.40.900",
            }
        ],
        opportunities=[
            {
                "id": 190,
                "procurement_id": 20228,
                "commercial_category_code": "flooring",
                "opportunity_track": "DIRECT_SUPPLY",
                "commercial_state": "ACTIVE",
                "last_source_event": "OPEN",
            }
        ],
        existing_audit=[],
    )
    assert updated[0]["commercial_state"] == CommercialOpportunityState.FOLLOW_UP_AWARDED.value
    assert audit[0]["reason"] == "FOLLOWUP_AWARDED"


def test_awarded_direct_supply_closed_not_prequalified() -> None:
    decision = _compute_decision(
        track="DIRECT_SUPPLY", source_event=SourceLifecycleEvent.AWARDED
    )
    assert decision.commercial_state == CommercialOpportunityState.CLOSED
    assert decision.reason == "DIRECT_SUPPLY_CLOSED"
    obj = build_manager_object(
        {
            "procurement_id": 99,
            "title": "Поставка компьютеров",
            "lifecycle": "AWARDED",
            "routing_mode": "DIRECT_OR_OTHER",
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "winner": "ООО Поставщик",
            "hypotheses": [
                {
                    "category": "computers",
                    "track": "DIRECT_SUPPLY",
                    "candidate_medal": "SILVER",
                    "final_score": 70,
                    "candidate_score": 70,
                }
            ],
        }
    )
    assert obj["workbench_status"] == WorkbenchCommercialState.CLOSED_DIRECT_SUPPLY.value
    assert obj["PREQUALIFIED_AWARDED"] is False
    assert obj["FOLLOW_UP_AWARDED"] is False
    assert obj["manager_actionability"] == ManagerActionability.NOT_ACTIONABLE.value
    assert obj["DOCUMENT_RESEARCH_REQUIRED_FOR_COMMERCIAL_ENTRY"] is False
    assert obj["winner"] == "ООО Поставщик"
    assert obj["candidate_categories"][0]["category"] == "computers"


def test_awarded_direct_supply_no_doc_job() -> None:
    assert (
        document_research_required_for_commercial_entry(
            opportunity_track="DIRECT_SUPPLY",
            source_event=SourceLifecycleEvent.AWARDED,
            procurement_form="DIRECT_GOODS_PURCHASE",
        )
        is False
    )
    q = dry_run_research_admission(
        procurement={
            "normalized_lifecycle": "AWARDED",
            "source_table": "reestr_contract_44_fz_awarded",
            "crm_stage": "razygranye",
            "award_status": "awarded",
        },
        opportunity_track="DIRECT_SUPPLY",
        research_action="PRIORITY_DOCS",
        routed=True,
        has_valid_category=True,
    )
    assert q.queue_eligible is False
    assert q.research_lane != "awarded_follow_up"
    assert q.reason == "AWARDED_DIRECT_SUPPLY_CLOSED"


def test_awarded_object_useful_runway_prequalified() -> None:
    clock = compute_execution_clock(
        delivery_start_at="2026-08-01",
        delivery_end_at="2027-03-12",
        as_of=date(2026, 8, 14),
    )
    obj = build_manager_object(
        {
            "procurement_id": 19572,
            "lifecycle": "AWARDED",
            "routing_mode": "OBJECT_MODE",
            "procurement_form": "CONSTRUCTION_WORKS",
            "winner": "ООО ВЕРТИКАЛЬ",
            "hypotheses": [
                {
                    "category": "drainage_water_management",
                    "track": "EMBEDDED_MATERIAL",
                    "candidate_medal": "SILVER",
                    "final_score": 64.8,
                    "candidate_score": 64.8,
                    "execution_clock": {
                        "execution_phase": clock.execution_phase.value,
                        "post_award_commercial_timing_value": clock.post_award_commercial_timing_value,
                    },
                }
            ],
        }
    )
    assert obj["PREQUALIFIED_AWARDED"] is True
    assert obj["workbench_status"] == WorkbenchCommercialState.PREQUALIFIED_AWARDED.value
    assert obj["FOLLOW_UP_AWARDED"] is True
    fu = _compute_decision(
        track="EMBEDDED_MATERIAL", source_event=SourceLifecycleEvent.AWARDED
    )
    assert fu.commercial_state == CommercialOpportunityState.FOLLOW_UP_AWARDED


def test_awarded_object_closing_not_closed_direct_supply() -> None:
    obj = build_manager_object(
        {
            "procurement_id": 20228,
            "lifecycle": "AWARDED",
            "routing_mode": "OBJECT_MODE",
            "procurement_form": "CONSTRUCTION_WORKS",
            "hypotheses": [
                {
                    "category": "flooring",
                    "track": "EMBEDDED_MATERIAL",
                    "candidate_medal": "WOOD",
                    "final_score": 48.9,
                    "candidate_score": 48.9,
                    "hard_cap": "WOOD",
                    "hard_cap_reason": "post_award_closing_execution_phase",
                    "execution_clock": {"execution_phase": "CLOSING"},
                }
            ],
        }
    )
    assert obj["workbench_status"] == WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED.value
    assert obj["workbench_status"] != WorkbenchCommercialState.CLOSED_DIRECT_SUPPLY.value
    assert obj["PREQUALIFIED_AWARDED"] is False


def test_no_okpd_prefix_lifecycle_router_in_authorities() -> None:
    root = Path(__file__).resolve().parents[1]
    files = [
        root / "src/services/commercial_routing_v3/opportunity_lifecycle_sync.py",
        root / "src/services/commercial_routing_v3/manager_object_ranking.py",
        root / "src/services/commercial_routing_v3/research_queue_lifecycle.py",
    ]
    banned = ('startswith("42', "startswith('42", 'startswith("71', 'startswith("26')
    found = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        found += sum(1 for token in banned if token in text)
    assert found == 0


def test_18215_nce_regression() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "procurement_id": 18215,
        "title": "Поставка счетчиков газа",
        "okpd_codes": ["26.51.63.110"],
        "CONTEXTUAL_RESEARCH_PRIORS": [],
        "normalized_lifecycle": "OPEN",
    }
    proc = model_input_as_prompt_procurement(mi)
    proc["v3_model_input"] = mi
    out = enrich_object_mode_routing(
        normalize_v3_output(
            {
                "procurement_form": "DIRECT_GOODS_PURCHASE",
                "commercial_category_hypotheses": [],
                "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
                "overall_research_action": "SKIP",
            },
            allowed_categories=ALLOWED,
            allowed_subcategories={},
            has_okpd=True,
        ),
        proc,
        allowed_categories=ALLOWED,
    )
    assert out["empty_hypothesis_status"] == "NO_COMMERCIAL_ENTRY"
    obj = build_manager_object(
        {
            "procurement_id": 18215,
            "lifecycle": "OPEN",
            "routing_mode": "DIRECT_OR_OTHER",
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
            "hypotheses": [],
        }
    )
    assert obj["workbench_status"] == WorkbenchCommercialState.NO_COMMERCIAL_ENTRY.value


def test_10753_object_mode_regression() -> None:
    mi = {
        "model_input_version": "V3_ROUTING_MODEL_INPUT_V3",
        "title": "Ликвидация деформаций покрытия автомобильной дороги",
        "okpd_codes": ["42.11"],
        "normalized_lifecycle": "OPEN",
        "CONTEXTUAL_RESEARCH_PRIORS": [{"category": "drainage_water_management", "weight": 50}],
    }
    proc = model_input_as_prompt_procurement(mi)
    proc["v3_model_input"] = mi
    out = enrich_object_mode_routing(
        normalize_v3_output(
            {
                "procurement_form": "CONSTRUCTION_WORKS",
                "commercial_category_hypotheses": [],
                "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
            },
            allowed_categories=ALLOWED,
            allowed_subcategories={},
            has_okpd=True,
        ),
        proc,
        allowed_categories=ALLOWED,
    )
    assert out["routing_mode"] == "OBJECT_MODE"
    tracks = {h.get("opportunity_track") for h in out["commercial_category_hypotheses"]}
    assert "DIRECT_SUPPLY" not in tracks


def test_awarded_direct_goods_priority_is_history_not_followup() -> None:
    prio = proposed_routing_priority(
        {
            "normalized_lifecycle": "AWARDED",
            "COMMERCIAL_PRODUCT_PRIORS": [{"category": "computers"}],
            "CONTEXTUAL_RESEARCH_PRIORS": [],
        }
    )
    assert prio["routing_lane"] == "AWARDED_HISTORY"
    obj_prio = proposed_routing_priority(
        {
            "normalized_lifecycle": "AWARDED",
            "COMMERCIAL_PRODUCT_PRIORS": [],
            "CONTEXTUAL_RESEARCH_PRIORS": [{"category": "flooring"}],
        }
    )
    assert obj_prio["routing_lane"] == "AWARDED_FOLLOWUP"


def test_generic_product_branch_lighting_not_computers_only() -> None:
    resolved = resolve_direct_goods_product_family(
        procurement_form="DIRECT_GOODS_PURCHASE",
        exact_okpd="27.40.11.110",
        priors=[LIGHTING_PRODUCT, COMPUTERS_BRANCH],
        ancestry_codes=["27.40.11.110", "27.40.11", "27.40", "27"],
        title="Поставка светильников",
    )
    assert resolved["commercial_category_code"] == "lighting"
    assert resolved["opportunity_track"] == "DIRECT_SUPPLY"
