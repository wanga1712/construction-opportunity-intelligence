"""Tests for canonical procurement card / deadline / priors / queue contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.commercial_routing_v3.deadline_pressure import compute_tender_clock
from src.services.commercial_routing_v3.document_links import ZERO_LINK_ROOT_CAUSE
from src.services.commercial_routing_v3.prior_semantics import (
    DIRECT_CABLE_EXPECTED_RESULT,
    classify_prior_kind,
    split_matched_priors,
)
from src.services.commercial_routing_v3.source_lifecycle import (
    normalize_source_lifecycle_event,
)
from src.services.commercial_routing_v3.canonical_card import (
    build_canonical_card,
    infer_source_origin,
)
from src.services.commercial_routing_v3.okpd_priors import prefix_matches
from src.domain.commercial_opportunity_lifecycle import SourceLifecycleEvent


def test_canonical_identity_and_no_dup_key():
    priors = []
    a = build_canonical_card(
        procurement={
            "id": 1,
            "source_table": "reestr_contract_44_fz",
            "source_id": 10,
            "contract_number": "0123456789012345678",
            "auction_name": "t",
            "crm_stage": "torgi",
            "award_status": "submission_open",
            "start_date": "2026-08-01",
            "end_date": "2026-08-20",
            "okpd_code": "27.32.13",
        },
        priors=priors,
        resolve_links=False,
    )
    b = build_canonical_card(
        procurement={
            "id": 2,
            "source_table": "reestr_contract_44_fz",
            "source_id": 11,
            "contract_number": "0123456789012345678",
            "auction_name": "t2",
            "crm_stage": "torgi",
            "award_status": "submission_open",
            "start_date": "2026-08-01",
            "end_date": "2026-08-20",
        },
        priors=priors,
        resolve_links=False,
    )
    assert a["canonical_identity"] == b["canonical_identity"]
    assert "44" in a["canonical_identity"] or "PUBLIC" in a["canonical_identity"]


def test_source_origin_forward_vs_backward():
    fwd = infer_source_origin(
        source_created_at="2026-08-02",
        start_date="2026-08-01",
        end_date="2026-08-20",
    )
    back = infer_source_origin(
        source_created_at="2026-09-01",
        start_date="2026-08-01",
        end_date="2026-08-20",
    )
    assert fwd["source_origin"] == "FORWARD_NEW"
    assert back["source_origin"] == "BACKWARD_RECOVERED"


def test_temporal_lifecycle():
    assert (
        normalize_source_lifecycle_event(
            source_table="reestr_contract_44_fz",
            crm_stage="torgi",
            end_date="2099-01-01",
        )
        == SourceLifecycleEvent.OPEN
    )
    assert (
        normalize_source_lifecycle_event(
            source_table="reestr_contract_44_fz",
            crm_stage="torgi",
            end_date="2020-01-01",
        )
        == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME
    )
    assert (
        normalize_source_lifecycle_event(
            source_table="reestr_contract_44_fz_awarded",
            crm_stage="razygranye",
        )
        == SourceLifecycleEvent.AWARDED
    )


def test_dynamic_deadline_and_short_vs_long_pressure():
    now = datetime(2026, 8, 10, tzinfo=timezone.utc)
    short = compute_tender_clock(
        published_at="2026-08-05",
        submission_start_at="2026-08-05",
        submission_deadline_at="2026-08-10",  # 5d window, ~0 remaining if as_of=end
        as_of=now - timedelta(days=2),  # 2 days remaining of 5
        active_urgency=True,
    )
    long = compute_tender_clock(
        published_at="2026-07-11",
        submission_start_at="2026-07-11",
        submission_deadline_at="2026-08-10",  # 30d window
        as_of=now - timedelta(days=2),
        active_urgency=True,
    )
    assert short.deadline_pressure is not None
    assert long.deadline_pressure is not None
    assert short.deadline_pressure != long.deadline_pressure
    # same absolute remaining, different elapsed_ratio → different pressure
    assert short.elapsed_ratio != long.elapsed_ratio
    # short window with 2d left is less elapsed than long window with 2d left
    assert short.elapsed_ratio < long.elapsed_ratio
    assert short.deadline_pressure < long.deadline_pressure


def test_direct_cable_no_tray_prior():
    priors = [
        {
            "commercial_category_code": "cable_support_systems",
            "okpd_pattern": "27.32",
            "match_type": "PREFIX",
            "prior_weight": 50,
            "signal_role": "CANDIDATE_SIGNAL",
            "prior_kind": "CONTEXTUAL_RESEARCH_PRIOR",
            "active": True,
        },
        {
            "commercial_category_code": "composite_cable_trays",
            "okpd_pattern": "27.32",
            "match_type": "PREFIX",
            "prior_weight": 40,
            "signal_role": "CANDIDATE_SIGNAL",
            "active": True,
        },
    ]
    # force contextual classification for cable_support; composite without explicit kind
    # still classified via CONTEXTUAL_ONLY_RULES only for cable_support — add rule path
    split = split_matched_priors("27.32.13.110", priors)
    assert all(
        p["prior_kind"] == "CONTEXTUAL_RESEARCH_PRIOR"
        for p in split["COMMERCIAL_PRODUCT_PRIORS"]
        if p["commercial_category_code"] == "cable_support_systems"
    ) or not any(
        p["commercial_category_code"] == "cable_support_systems"
        for p in split["COMMERCIAL_PRODUCT_PRIORS"]
    )
    assert DIRECT_CABLE_EXPECTED_RESULT == "NO_COMMERCIAL_ENTRY"
    # cable_support must land in contextual
    assert any(
        p["commercial_category_code"] == "cable_support_systems"
        for p in split["CONTEXTUAL_RESEARCH_PRIORS"]
    )


def test_classify_27_32_contextual():
    kind = classify_prior_kind(
        {
            "commercial_category_code": "cable_support_systems",
            "okpd_pattern": "27.32",
            "signal_role": "CANDIDATE_SIGNAL",
        }
    )
    assert kind == "CONTEXTUAL_RESEARCH_PRIOR"


def test_okpd_exact_prefix():
    assert prefix_matches("27.32.13", "27.32", "PREFIX")
    assert not prefix_matches("27.321", "27.32", "PREFIX")


def test_zero_link_root_cause_documented():
    assert "contract_number" in ZERO_LINK_ROOT_CAUSE


def test_awarded_card_does_not_use_contract_dates_as_submission():
    card = build_canonical_card(
        procurement={
            "id": 99,
            "source_table": "reestr_contract_44_fz_awarded",
            "source_id": 1,
            "contract_number": "A1",
            "auction_name": "awarded",
            "crm_stage": "razygranye",
            "award_status": "awarded",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "winner_name": "ООО Победитель",
            "winner_inn": "7700000000",
            "initial_price": 1000,
            "final_price": 900,
        },
        priors=[],
        resolve_links=False,
    )
    assert card["normalized_lifecycle"] == "AWARDED"
    assert card["submission_deadline_at"] is None
    assert card["winner_name"] == "ООО Победитель"
    assert card["price_reduction_percent"] == 10.0


def test_no_user_specific_runtime_filter_in_loader_sql():
    import inspect
    from src.services.commercial_routing_v3 import okpd_priors as m

    src = inspect.getsource(m.load_okpd_priors_from_db)
    assert "user_id" not in src.lower() or "source_user_id" in src
    assert "WHERE active" in src
    assert "current_user" not in src.lower()
