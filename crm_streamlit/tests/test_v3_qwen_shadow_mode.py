"""Shadow mode: Qwen must not auto-accept into CURRENT opportunities."""
from __future__ import annotations

from src.services.commercial_routing_v3.decision_authorities import (
    EXPERT_ANNOTATION,
    MODEL_RAW_DECISION,
    automatic_model_acceptance_enabled,
    qwen_candidate_inference_enabled,
    qwen_shadow_mode,
)
from src.services.commercial_routing_v3.opportunity_persistence import (
    has_expert_lock,
    persist_category_opportunities,
)


class _Db:
    def execute_scalar(self, *_a, **_k):
        sql = _a[0] if _a else ""
        if "expert_annotations" in str(sql):
            return None
        return True

    def execute_update(self, *_a, **_k):
        raise AssertionError("shadow must not write CURRENT opportunities")


def test_shadow_does_not_promote_current(monkeypatch) -> None:
    monkeypatch.setenv("CRM_V3_QWEN_SHADOW_MODE", "1")
    assert qwen_shadow_mode() is True
    out = persist_category_opportunities(
        _Db(),
        procurement_id=17285,
        assessment_id=1,
        normalized_result={"routing_version": "v3", "model_name": "qwen2.5:7b"},
        category_opportunities=[
            {
                "category_code": "computers",
                "opportunity_track": "DIRECT_SUPPLY",
                "candidate_medal": "SILVER",
                "research_action": "LIGHT_RESEARCH",
                "confidence": 0.8,
            }
        ],
        dry_run=False,
    )
    assert out["persisted"] == 0
    assert out["accepted_untouched"] is True
    assert out["authority"] == MODEL_RAW_DECISION
    assert out["proposed"] == 1


def test_expert_lock_blocks_current_overwrite() -> None:
    class _Db:
        def execute_scalar(self, *_a, **_k):
            return 1

        def execute_update(self, *_a, **_k):
            raise AssertionError("expert lock must not write CURRENT")

    out = persist_category_opportunities(
        _Db(),
        procurement_id=99,
        assessment_id=1,
        normalized_result={"routing_version": "v3"},
        category_opportunities=[
            {"category_code": "computers", "opportunity_track": "DIRECT_SUPPLY", "candidate_medal": "GOLD"}
        ],
        dry_run=False,
    )
    assert out["expert_locked"] is True
    assert out["accepted_untouched"] is True
    assert out["persisted"] == 0
    assert out["authority"] == EXPERT_ANNOTATION
    out = persist_category_opportunities(
        _Db(),
        procurement_id=1,
        assessment_id=1,
        normalized_result={"routing_version": "v3"},
        category_opportunities=[],
        dry_run=True,
    )
    assert out["dry_run"] is True


def test_qwen_candidate_inference_can_be_frozen(monkeypatch) -> None:
    monkeypatch.delenv("CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED", raising=False)
    assert qwen_candidate_inference_enabled() is True
    monkeypatch.setenv("CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED", "0")
    assert qwen_candidate_inference_enabled() is False
    monkeypatch.setenv("CRM_V3_QWEN_SHADOW_MODE", "1")
    assert automatic_model_acceptance_enabled() is False


def test_automatic_acceptance_off_when_inference_frozen(monkeypatch) -> None:
    monkeypatch.setenv("CRM_V3_QWEN_SHADOW_MODE", "0")
    monkeypatch.setenv("CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED", "0")
    assert automatic_model_acceptance_enabled() is False


def test_has_expert_lock_true_and_false() -> None:
    class _Yes:
        def execute_scalar(self, *_a, **_k):
            return 1

    class _No:
        def execute_scalar(self, *_a, **_k):
            return None

    assert has_expert_lock(_Yes(), 1) is True
    assert has_expert_lock(_No(), 1) is False
