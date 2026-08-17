"""Tests for V3 golden canary boot arm — MUST NOT call Qwen."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.services.commercial_routing_v3 import golden_canary_config as cfg
from src.services.commercial_routing_v3 import golden_canary_runner as runner
from src.services.commercial_routing_v3 import golden_canary_validate as validate
from src.services.commercial_routing_v3.golden_canary_readiness import ReadinessResult
from src.services.commercial_routing_v3.golden_canary_select import ReferenceExpectation


def test_invariants_no_queue_no_batch():
    assert cfg.MAX_PROCUREMENTS_PROCESSED == 4
    assert cfg.QUEUE_GENERATED is False
    assert cfg.DOCUMENT_PROCESSING_RUN is False
    assert cfg.BATCH_ROUTING_TRIGGERED is False
    assert cfg.CANARY_RUN_MAX_ONCE is True


def test_runner_imports():
    assert callable(runner.run_golden_canary)
    assert callable(runner.arm_status_only)
    assert callable(runner.marker_exists)


def test_marker_prevents_second_run(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CANARY_DIR", tmp_path)
    monkeypatch.setattr(runner, "MARKER_PATH", tmp_path / "done")
    monkeypatch.setattr(runner, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(runner, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(runner, "REFERENCE_PATH", tmp_path / "ref.json")
    (tmp_path / "done").write_text("{}", encoding="utf-8")

    called = {"qwen": False}

    def boom(*a, **k):
        called["qwen"] = True
        raise AssertionError("must not call model")

    out = runner.run_golden_canary(
        crm_db=MagicMock(),
        tender_db=MagicMock(),
        execute_qwen=True,
        skip_readiness_sleep=True,
        generate_json_fn=boom,
    )
    assert out["final_verdict"] == cfg.STATUS_SKIPPED
    assert called["qwen"] is False
    assert out["qwen_procurement_count"] == 0


def test_readiness_fail_stops_model(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CANARY_DIR", tmp_path)
    monkeypatch.setattr(runner, "MARKER_PATH", tmp_path / "done")
    monkeypatch.setattr(runner, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(runner, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(runner, "REFERENCE_PATH", tmp_path / "ref.json")

    bad = ReadinessResult(ok=False, failures=["OLLAMA_UNREACHABLE"])

    def boom(*a, **k):
        raise AssertionError("model must not run")

    with patch.object(runner, "evaluate_readiness", return_value=bad):
        out = runner.run_golden_canary(
            crm_db=MagicMock(),
            tender_db=MagicMock(),
            execute_qwen=True,
            skip_readiness_sleep=True,
            generate_json_fn=boom,
        )
    assert out["final_verdict"] == "FAIL"
    assert out["fail_reason"] == "READINESS_GATE"
    assert out["qwen_procurement_count"] == 0
    assert (tmp_path / "done").exists()


def test_max_count_enforced_on_execute(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CANARY_DIR", tmp_path)
    monkeypatch.setattr(runner, "MARKER_PATH", tmp_path / "done")
    monkeypatch.setattr(runner, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(runner, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(runner, "REFERENCE_PATH", tmp_path / "ref.json")

    refs = [
        ReferenceExpectation(
            case_key=k,
            case_label=k,
            procurement_id=i,
            contract_number=str(i),
            auction_name="t",
            okpd_code="27.40",
            okpd_name="x",
            expected_category="lighting" if k.startswith("A") else "*",
            expected_tracks=["DIRECT_SUPPLY"] if k.startswith("A") else ["EMBEDDED_MATERIAL"],
            expected_form_hint="X",
            selection_score=90,
            selection_rationale="t",
            before_qwen=True,
        )
        for i, k in enumerate(["A", "B", "C", "D", "E"], start=1)
    ]

    ready = ReadinessResult(ok=True)
    calls = {"n": 0}

    def fake_gen(prompt, timeout=180):
        calls["n"] += 1
        return {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "commercial_category_hypotheses": [
                {
                    "category_code": "lighting",
                    "subcategory_code": None,
                    "opportunity_track": "DIRECT_SUPPLY",
                    "confidence": 0.9,
                    "reason_codes": ["okpd"],
                    "positive_evidence": ["title"],
                    "negative_evidence": [],
                }
            ],
            "material_signals": [],
            "work_methods": [],
            "application_areas": [],
            "object_context": [],
            "brands": [],
            "discovery_required": False,
            "analysis_modes": ["GENERAL_DISCOVERY"],
        }

    class FakeEngine:
        def _load_priors(self):
            return []

        def load_registry(self):
            return ([{"category_code": "lighting"}], {"lighting", "computers"}, {"lighting": set()})

        def build_prompt_context(self, procurement):
            return "PROMPT"

        def route_with_ai(self, procurement, ai_raw, **kw):
            from src.domain.commercial_routing_v3 import (
                AnalysisMode,
                CandidateMedal,
                CategoryOpportunityV3,
                CategoryValueBasis,
                OpportunityTrack,
                ProcurementForm,
                ResearchAction,
                RoutingDecisionV3,
                SourceContour,
            )

            return RoutingDecisionV3(
                source_contour=SourceContour.PUBLIC_44FZ,
                procurement_form=ProcurementForm.DIRECT_GOODS_PURCHASE,
                analysis_modes=[AnalysisMode.GENERAL_DISCOVERY],
                commercial_category_hypotheses=[
                    CategoryOpportunityV3(
                        commercial_category_code="lighting",
                        commercial_subcategory_code=None,
                        opportunity_track=OpportunityTrack.DIRECT_SUPPLY,
                        category_confidence=0.9,
                        research_action=ResearchAction.SKIP,
                        research_priority=0,
                        commercial_priority_score=0,
                        research_value_score=0,
                        candidate_medal=CandidateMedal.GOLD,
                        expected_category_value=None,
                        category_value_basis=CategoryValueBasis.DIRECT_PROCUREMENT_VALUE,
                        reason_codes=["okpd"],
                        positive_evidence=["title"],
                        negative_evidence=[],
                    )
                ],
                discovery_required=False,
                overall_research_action=ResearchAction.SKIP,
                model_name="test",
            )

    with patch.object(runner, "evaluate_readiness", return_value=ready), patch.object(
        runner, "select_four_reference_cases", return_value=refs[:4]
    ), patch.object(runner, "CommercialRoutingV3Engine", return_value=FakeEngine()), patch.object(
        runner, "load_procurement_for_routing", return_value={"id": 1, "auction_name": "t", "okpd_code": "27.40"}
    ), patch.object(runner, "configured_model", return_value="qwen-test"):
        out = runner.run_golden_canary(
            crm_db=MagicMock(),
            tender_db=MagicMock(),
            execute_qwen=True,
            skip_readiness_sleep=True,
            generate_json_fn=fake_gen,
        )
    assert out["qwen_procurement_count"] == 4
    assert calls["n"] == 4
    assert out["QUEUE_GENERATED"] is False
    assert out["BATCH_ROUTING_TRIGGERED"] is False
    assert out["AI_TIMER_ENABLED_BY_CANARY"] is False


def test_pass_does_not_trigger_batch_flags():
    assert cfg.BATCH_ROUTING_TRIGGERED is False
    # PASS policy encoded: runner never flips these
    assert runner.BATCH_ROUTING_TRIGGERED is False


def test_validate_wrong_track_fails():
    ref = ReferenceExpectation(
        case_key="A_DIRECT_LIGHTING",
        case_label="L",
        procurement_id=1,
        contract_number="1",
        auction_name="Поставка светильников",
        okpd_code="27.40.1",
        okpd_name="свет",
        expected_category="lighting",
        expected_tracks=["DIRECT_SUPPLY"],
        expected_form_hint="DIRECT_GOODS_PURCHASE",
        selection_score=90,
        selection_rationale="t",
    )
    out = {
        "procurement_form": "CONSTRUCTION_WORKS",
        "commercial_category_hypotheses": [
            {
                "category_code": "lighting",
                "subcategory_code": None,
                "subcategory_status": "SUBCATEGORY_NOT_ASSIGNED",
                "opportunity_track": "EMBEDDED_MATERIAL",
            }
        ],
        "material_signals": [],
        "work_methods": [],
        "application_areas": [],
        "object_context": [],
        "brands": [],
        "discovery_required": False,
        "subcategory_explicit_ok": True,
    }
    v = validate.validate_case(ref, out, allowed_categories={"lighting"})
    assert v["verdict"] == "FAIL"


def test_systemd_unit_file_exists():
    unit = Path(__file__).resolve().parents[1] / "deploy" / "crm-v3-golden-canary-onboot.service"
    text = unit.read_text(encoding="utf-8")
    assert "Type=oneshot" in text
    assert "run_v3_golden_canary_once.py --boot" in text
    assert "postgresql@17-main.service" in text
    assert "ollama.service" in text
    assert "ConditionPathExists=!/var/lib/crm-v3-canary/golden_canary_20260813.done" in text
    assert "WantedBy=multi-user.target" in text


def test_manual_ignores_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CANARY_DIR", tmp_path)
    monkeypatch.setattr(runner, "MARKER_PATH", tmp_path / "done")
    monkeypatch.setattr(runner, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(runner, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(runner, "REFERENCE_PATH", tmp_path / "ref.json")
    (tmp_path / "done").write_text("{}", encoding="utf-8")

    ready = ReadinessResult(ok=False, failures=["STOP_BEFORE_MODEL"])

    with patch.object(runner, "evaluate_readiness", return_value=ready):
        out = runner.run_golden_canary(
            crm_db=MagicMock(),
            tender_db=MagicMock(),
            execute_qwen=True,
            skip_readiness_sleep=True,
            ignore_marker=True,
            generate_json_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model")),
        )
    # With ignore_marker, marker does not skip; readiness fail stops before model
    assert out.get("skipped") is not True
    assert out["fail_reason"] == "READINESS_GATE"
    assert out["qwen_procurement_count"] == 0


def test_script_has_manual_mode():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "run_v3_golden_canary_once.py").read_text(
        encoding="utf-8"
    )
    assert "--manual" in src
    assert "ignore_marker" in src


def test_script_has_no_ai_timer_enable():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "run_v3_golden_canary_once.py").read_text(
        encoding="utf-8"
    )
    assert "systemctl start crm-ai" not in src
    assert "systemctl enable crm-ai" not in src
    assert "queue_producer" not in src.lower()
