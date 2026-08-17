"""CRM-V3-MEDAL-LINEAGE-DAILY-REEVALUATION-AND-INFERENCE-RELIABILITY-1 tests."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.domain.commercial_routing_v3 import CandidateMedal
from src.services.ai_client import generate_v3_routing_with_bounded_retry
from src.services.commercial_routing_v3.daily_medal_reevaluation import (
    reevaluate_many,
    reevaluate_opportunity,
)
from src.services.commercial_routing_v3.manager_lane_gates import split_actionable_lanes
from src.services.commercial_routing_v3.manager_object_ranking import (
    WorkbenchCommercialState,
    build_manager_object,
    rank_manager_objects,
)
from src.services.commercial_routing_v3.medal_lineage import (
    INITIAL_PROVENANCE_FIRST,
    REASON_ACTIVE_DECAY,
    REASON_AWARDED_DECAY,
    REASON_OPEN_TO_AWARDED,
    REASON_SOURCE_CHANGE,
    apply_synthetic_confirmation,
    first_acceptance_lineage,
    manager_lineage_card_fields,
    preserve_initial_on_lifecycle_change,
    ranking_medal_and_score,
    recalculate_current_effective_priority,
    scoring_ctx_from_timing,
)
from src.services.commercial_routing_v3.model_json import (
    V3_INFERENCE_STATE_FORMAT_FAILED,
    ModelFormatError,
    ModelInferenceFormatFailed,
    extract_routing_json,
)
from src.services.commercial_routing_v3.post_award_execution_timing import (
    ExecutionPhase,
    compute_execution_clock,
)

_RANK = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1}


def _hyp(**over):
    row = {
        "category_code": "drainage_water_management",
        "opportunity_track": "EMBEDDED_MATERIAL",
        "evidence_role": "COMMERCIAL_PRODUCT_PRIOR",
        "confirmation_required": False,
        "confidence": 0.92,
    }
    row.update(over)
    return row


def _active_ctx(*, remaining: float, timing: float):
    return scoring_ctx_from_timing(
        procurement_form="CONSTRUCTION_WORKS",
        routing_mode="OBJECT_MODE",
        lifecycle="OPEN",
        object_classification={"object_type": "ROAD"},
        commercial_timing_value=timing,
        remaining_days=remaining,
        initial_price=50_000_000,
    )


def _awarded_ctx(as_of: date):
    clock = compute_execution_clock(
        delivery_start_at="2026-01-01",
        delivery_end_at="2026-12-31",
        as_of=as_of,
    )
    return scoring_ctx_from_timing(
        procurement_form="CONSTRUCTION_WORKS",
        routing_mode="OBJECT_MODE",
        lifecycle="AWARDED",
        object_classification={"object_type": "ROAD"},
        commercial_timing_value=None,
        remaining_days=None,
        execution_clock=clock,
        initial_price=50_000_000,
        final_contract_price=48_000_000,
    ), clock


def _accept(hyp, ctx, now=None):
    from src.services.commercial_routing_v3.candidate_scoring import score_hypothesis

    result = score_hypothesis(hyp, ctx)
    return first_acceptance_lineage(
        hyp,
        score=result.final_score,
        medal=result.candidate_medal.value,
        now=now or datetime(2026, 1, 15, tzinfo=timezone.utc),
    ), result


def test_extract_markdown_fenced_json_not_review() -> None:
    parsed, method = extract_routing_json(
        '```json\n{"procurement_form": "CONSTRUCTION_WORKS"}\n```\n'
    )
    assert parsed["procurement_form"] == "CONSTRUCTION_WORKS"
    assert method == "markdown_fence"


def test_extract_prefix_suffix_prose() -> None:
    parsed, method = extract_routing_json(
        'Here is the JSON:\n{"ok": true, "category_code": "lighting"}\nThanks.'
    )
    assert parsed == {"ok": True, "category_code": "lighting"}
    assert method in {"balanced_object", "raw"}


def test_extract_does_not_invent_fields() -> None:
    parsed, _ = extract_routing_json('{"a": 1}')
    assert parsed == {"a": 1}


def test_empty_and_truncated_classes() -> None:
    with pytest.raises(ModelFormatError) as empty:
        extract_routing_json("   ")
    assert empty.value.failure_class == "EMPTY_RESPONSE"
    with pytest.raises(ModelFormatError) as trunc:
        extract_routing_json('{"procurement_form": "CONSTRUCTION_WORKS", "hypotheses": [')
    assert trunc.value.failure_class == "TRUNCATED_RESPONSE"


def test_schema_invalid_json_array() -> None:
    with pytest.raises(ModelFormatError) as err:
        extract_routing_json("[1, 2]")
    assert err.value.failure_class == "SCHEMA_INVALID_JSON"


def test_bounded_retry_telemetry_recovers(monkeypatch) -> None:
    n = {"i": 0}

    def fake_v3(prompt, **kwargs):
        n["i"] += 1
        if n["i"] < 3:
            return "not-json", {"model": "qwen2.5:7b", "request_model": "qwen2.5:7b"}
        return '{"ok": true}', {"model": "qwen2.5:7b", "request_model": "qwen2.5:7b"}

    monkeypatch.setattr("src.services.ai_client.generate_v3_routing", fake_v3)
    parsed, meta, retries = generate_v3_routing_with_bounded_retry(
        "{}", input_hash="abc", prompt_version="v5"
    )
    assert parsed == {"ok": True}
    assert retries == 2
    assert meta["attempt_count"] == 3
    assert [h["status"] for h in meta["attempt_history"]] == ["FAIL", "FAIL", "OK"]
    assert meta["same_prompt_hash"] is True
    assert meta["same_model"] is True
    assert meta["model_format_retry_count"] == 2


def test_persistent_format_failure_durable_state(monkeypatch) -> None:
    def fake_v3(prompt, **kwargs):
        return "nope", {"model": "qwen2.5:7b", "request_model": "qwen2.5:7b"}

    monkeypatch.setattr("src.services.ai_client.generate_v3_routing", fake_v3)
    with pytest.raises(ModelInferenceFormatFailed) as err:
        generate_v3_routing_with_bounded_retry("{}", procurement_id=13264, input_hash="h")
    assert err.value.durable_state["status"] == V3_INFERENCE_STATE_FORMAT_FAILED
    assert err.value.durable_state["attempt_count"] == 3
    assert err.value.meta["model_format_retry_count"] == 2
    assert len(err.value.attempt_history) == 3


def test_medal_initial_persistence() -> None:
    hyp = _hyp()
    lin, result = _accept(hyp, _active_ctx(remaining=25, timing=100))
    assert result.candidate_medal == CandidateMedal.GOLD
    lin2, hist, qwen = recalculate_current_effective_priority(
        lin, _active_ctx(remaining=2, timing=20), reason=REASON_ACTIVE_DECAY, procurement_id=1
    )
    assert qwen == 0
    assert lin2.candidate_initial_medal == CandidateMedal.GOLD.value
    assert lin2.candidate_initial_score == result.final_score
    assert lin2.initial_medal_provenance == INITIAL_PROVENANCE_FIRST
    assert hist is not None
    assert (
        lin2.current_effective_medal != CandidateMedal.GOLD.value
        or lin2.current_effective_score < result.final_score
    )


def test_confirmed_base_persistence() -> None:
    hyp = _hyp()
    lin, result = _accept(hyp, _active_ctx(remaining=25, timing=100))
    apply_synthetic_confirmation(
        lin, confirmed_score=result.final_score, confirmed_medal=result.candidate_medal.value
    )
    lin2, _, qwen = recalculate_current_effective_priority(
        lin, _active_ctx(remaining=2, timing=20), reason=REASON_ACTIVE_DECAY, procurement_id=1
    )
    assert qwen == 0
    assert lin2.confirmed_base_medal == CandidateMedal.GOLD.value
    assert lin2.confirmed_base_score == result.final_score


def test_current_effective_medal_and_card() -> None:
    hyp = _hyp()
    lin, _ = _accept(hyp, _active_ctx(remaining=25, timing=100))
    lin, _, _ = recalculate_current_effective_priority(
        lin, _active_ctx(remaining=0.4, timing=10), reason=REASON_ACTIVE_DECAY, procurement_id=1
    )
    card = manager_lineage_card_fields(lin)
    assert card["CURRENT_MEDAL"] == lin.current_effective_medal
    assert card["candidate_initial_medal"] == CandidateMedal.GOLD.value
    medal, score = ranking_medal_and_score(
        {
            "candidate_medal": lin.candidate_initial_medal,
            "final_score": lin.candidate_initial_score,
            "current_effective_medal": lin.current_effective_medal,
            "current_effective_score": lin.current_effective_score,
        }
    )
    assert medal == lin.current_effective_medal
    assert score == lin.current_effective_score


def test_active_time_decay_matrix() -> None:
    hyp = _hyp()
    lin, first = _accept(hyp, _active_ctx(remaining=28, timing=100))
    assert first.candidate_medal == CandidateMedal.GOLD
    medals = [first.candidate_medal.value]
    for remaining, timing in ((6, 45), (2, 20), (0.4, 10), (-1, 10)):
        lin, hist, qwen = recalculate_current_effective_priority(
            lin,
            _active_ctx(remaining=remaining, timing=timing),
            reason=REASON_ACTIVE_DECAY,
            procurement_id=10,
        )
        assert qwen == 0
        medals.append(lin.current_effective_medal)
        if hist is None:
            continue
        assert hist["reason"] == REASON_ACTIVE_DECAY
    assert lin.candidate_initial_medal == CandidateMedal.GOLD.value
    ranks = [_RANK[m] for m in medals]
    assert ranks == sorted(ranks, reverse=True)
    assert medals[0] == "GOLD"
    assert medals[-1] != "GOLD"


def test_active_silver_never_becomes_gold_from_time() -> None:
    hyp = _hyp(evidence_role="CONTEXTUAL_RESEARCH_PRIOR")
    lin, first = _accept(hyp, _active_ctx(remaining=2, timing=20))
    assert first.candidate_medal != CandidateMedal.GOLD
    silverish = first.candidate_medal.value
    lin, _, _ = recalculate_current_effective_priority(
        lin, _active_ctx(remaining=28, timing=100), reason=REASON_ACTIVE_DECAY, procurement_id=11
    )
    assert lin.current_effective_medal == silverish
    assert _RANK[lin.current_effective_medal] <= _RANK[silverish]
    assert lin.current_effective_medal != CandidateMedal.GOLD.value


def test_awarded_time_decay_to_closing_wood() -> None:
    hyp = _hyp(evidence_role="CONTEXTUAL_RESEARCH_PRIOR")
    ctx_early, clock_early = _awarded_ctx(date(2026, 2, 10))
    assert clock_early.execution_remaining_ratio and clock_early.execution_remaining_ratio >= 0.80
    lin, first = _accept(hyp, ctx_early)
    assert first.candidate_medal == CandidateMedal.GOLD
    last_clock = clock_early
    last_hist = None
    for as_of in (date(2026, 7, 2), date(2026, 10, 10), date(2026, 12, 2)):
        ctx, clock = _awarded_ctx(as_of)
        lin, hist, qwen = recalculate_current_effective_priority(
            lin, ctx, reason=REASON_AWARDED_DECAY, procurement_id=12
        )
        assert qwen == 0
        last_clock = clock
        last_hist = hist
    assert lin.candidate_initial_medal == CandidateMedal.GOLD.value
    assert lin.current_effective_medal == CandidateMedal.WOOD.value
    assert last_clock.execution_phase == ExecutionPhase.CLOSING
    assert last_clock.execution_remaining_ratio is not None
    assert last_clock.execution_remaining_ratio <= 0.10
    assert last_hist is not None


def test_time_only_no_medal_improvement() -> None:
    hyp = _hyp()
    lin, _ = _accept(hyp, _active_ctx(remaining=2, timing=20))
    before = lin.current_effective_medal, lin.current_effective_score
    lin2, hist, _ = recalculate_current_effective_priority(
        lin, _active_ctx(remaining=28, timing=100), reason=REASON_ACTIVE_DECAY, procurement_id=13
    )
    assert (lin2.current_effective_medal, lin2.current_effective_score) == before
    assert hist is None
    lin3, hist3, _ = recalculate_current_effective_priority(
        lin2, _active_ctx(remaining=28, timing=100), reason=REASON_SOURCE_CHANGE, procurement_id=13
    )
    assert _RANK[lin3.current_effective_medal] >= _RANK[before[0]]
    assert hist3 is not None
    assert hist3["reason"] == REASON_SOURCE_CHANGE


def test_open_to_awarded_lineage_and_no_initial_reassignment() -> None:
    hyp = _hyp()
    lin, _ = _accept(hyp, _active_ctx(remaining=25, timing=100))
    initial = (
        lin.candidate_initial_medal,
        lin.candidate_initial_score,
        lin.candidate_initial_at,
        lin.initial_medal_provenance,
    )
    preserve_initial_on_lifecycle_change(lin)
    ctx, clock = _awarded_ctx(date(2026, 2, 10))
    lin2, hist, qwen = recalculate_current_effective_priority(
        lin, ctx, reason=REASON_OPEN_TO_AWARDED, procurement_id=14
    )
    assert qwen == 0
    assert (
        lin2.candidate_initial_medal,
        lin2.candidate_initial_score,
        lin2.candidate_initial_at,
        lin2.initial_medal_provenance,
    ) == initial
    assert initial[0] == CandidateMedal.GOLD.value
    assert hist is not None
    assert hist["reason"] == REASON_OPEN_TO_AWARDED
    assert clock.execution_phase == ExecutionPhase.EARLY_EXECUTION


def test_late_award_preserves_base_but_closes_current() -> None:
    hyp = _hyp()
    lin, _ = _accept(hyp, _active_ctx(remaining=25, timing=100))
    ctx, clock = _awarded_ctx(date(2026, 12, 2))
    lin2, _, _ = recalculate_current_effective_priority(
        lin, ctx, reason=REASON_OPEN_TO_AWARDED, procurement_id=15
    )
    assert lin2.candidate_initial_medal == CandidateMedal.GOLD.value
    assert lin2.current_effective_medal == CandidateMedal.WOOD.value
    assert clock.execution_phase == ExecutionPhase.CLOSING
    obj = build_manager_object(
        {
            "procurement_id": 15,
            "lifecycle": "AWARDED",
            "routing_mode": "OBJECT_MODE",
            "hypotheses": [
                {
                    "category": "drainage_water_management",
                    "candidate_medal": lin2.candidate_initial_medal,
                    "candidate_initial_medal": lin2.candidate_initial_medal,
                    "current_effective_medal": lin2.current_effective_medal,
                    "current_effective_score": lin2.current_effective_score,
                    "final_score": lin2.current_effective_score,
                    "hard_cap": "WOOD",
                    "hard_cap_reason": "post_award_closing_execution_phase",
                    "execution_clock": {
                        "execution_phase": "CLOSING",
                        "post_award_commercial_timing_value": 7.5,
                    },
                }
            ],
        }
    )
    assert obj["workbench_status"] == WorkbenchCommercialState.COMMERCIAL_WINDOW_CLOSED.value
    assert obj["CURRENT_MEDAL"] == "WOOD"
    assert obj["candidate_initial_medal"] == "GOLD"


def test_daily_reevaluation_no_qwen_and_idempotent() -> None:
    hyp = _hyp()
    lin, _ = _accept(hyp, _active_ctx(remaining=25, timing=100))
    row = {
        "procurement_id": 99,
        "lifecycle": "OPEN",
        "procurement_form": "CONSTRUCTION_WORKS",
        "routing_mode": "OBJECT_MODE",
        "object_classification": {"object_type": "ROAD"},
        "commercial_timing_value": 20,
        "remaining_days": 2,
        "initial_price": 50_000_000,
        **lin.as_dict(),
    }
    first = reevaluate_opportunity(row)
    assert first["qwen_calls"] == 0
    row.update(first["lineage"])
    second = reevaluate_opportunity(row)
    assert second["qwen_calls"] == 0
    assert second["history"] is None
    batch = reevaluate_many([row])
    assert batch["qwen_calls"] == 0
    assert batch["history_rows"] == []


def test_medal_history_transition_and_ranking_uses_effective() -> None:
    hyp = _hyp()
    lin, _ = _accept(hyp, _active_ctx(remaining=25, timing=100))
    lin, hist, _ = recalculate_current_effective_priority(
        lin, _active_ctx(remaining=2, timing=20), reason=REASON_ACTIVE_DECAY, procurement_id=21
    )
    assert hist is not None
    assert hist["previous_effective_medal"] == "GOLD"
    assert hist["new_effective_medal"] != "GOLD"
    gold_hist = build_manager_object(
        {
            "procurement_id": 1,
            "lifecycle": "OPEN",
            "hypotheses": [
                {
                    "category": "drainage_water_management",
                    "candidate_medal": "GOLD",
                    "candidate_initial_medal": "GOLD",
                    "current_effective_medal": "BRONZE",
                    "current_effective_score": 30.0,
                    "final_score": 30.0,
                }
            ],
        }
    )
    silver_now = build_manager_object(
        {
            "procurement_id": 2,
            "lifecycle": "OPEN",
            "hypotheses": [
                {
                    "category": "lighting",
                    "candidate_medal": "SILVER",
                    "current_effective_medal": "SILVER",
                    "current_effective_score": 60.0,
                    "final_score": 60.0,
                }
            ],
        }
    )
    actionable, _ = rank_manager_objects([gold_hist, silver_now])
    assert actionable[0]["procurement_id"] == 2


def test_top5_active_and_awarded_gates_separate() -> None:
    objs = []
    for i in range(6):
        objs.append(
            build_manager_object(
                {
                    "procurement_id": 100 + i,
                    "lifecycle": "OPEN",
                    "hypotheses": [
                        {
                            "category": "flooring",
                            "candidate_medal": "SILVER",
                            "current_effective_medal": "SILVER",
                            "current_effective_score": 70 - i,
                            "final_score": 70 - i,
                        }
                    ],
                }
            )
        )
    for i in range(6):
        objs.append(
            build_manager_object(
                {
                    "procurement_id": 200 + i,
                    "lifecycle": "AWARDED",
                    "routing_mode": "OBJECT_MODE",
                    "hypotheses": [
                        {
                            "category": "flooring",
                            "candidate_medal": "GOLD",
                            "current_effective_medal": "GOLD",
                            "current_effective_score": 80 - i,
                            "final_score": 80 - i,
                            "execution_clock": {"execution_phase": "EARLY_EXECUTION"},
                        }
                    ],
                }
            )
        )
    lanes = split_actionable_lanes(objs)
    assert len(lanes["TOP_5_ACTIVE"]) == 5
    assert len(lanes["TOP_5_AWARDED"]) == 5
    assert all(o["lifecycle"] == "OPEN" for o in lanes["TOP_5_ACTIVE"])
    assert all(o["lifecycle"] == "AWARDED" for o in lanes["TOP_5_AWARDED"])
    mixed, _ = rank_manager_objects(objs)
    assert mixed[0]["lifecycle"] == "AWARDED"
    assert lanes["TOP_5_ACTIVE"][0]["procurement_id"] == 100
