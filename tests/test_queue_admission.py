import inspect
import subprocess
import sys
from pathlib import Path

from tender_documents_research.document_processor.admission_policy import (
    admission_claim_sql,
    authority_allows_queue,
    queue_context_allows_claim,
)
from src.learning.procurement_scope.classifier import ProcurementScopeType
from src.services.procurement_research_admission import evaluate_admission


def test_authority_gate_is_explicit_and_fail_closed():
    assert authority_allows_queue({"admission_state": "ELIGIBLE"})
    assert not authority_allows_queue({"admission_state": "EXCLUDED"})
    assert not authority_allows_queue({"admission_state": "HOLD"})
    assert not authority_allows_queue(None)
    assert queue_context_allows_claim({"admission_state": "ELIGIBLE"})
    assert queue_context_allows_claim({"admission": {"admission_state": "ELIGIBLE"}})
    assert not queue_context_allows_claim({"admission_state": "HOLD"})
    assert not queue_context_allows_claim(None)


def test_business_admission_matrix_is_fail_closed_before_priority():
    cases = [
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "DIRECT_GOODS", True),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "WORKS_WITH_EMBEDDED_PRODUCTS", True),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "DESIGN_PROJECT", True),
        ({"crm_stage": "razygranye", "award_status": "awarded"}, "DIRECT_GOODS", False),
        ({"crm_stage": "torgi", "award_status": "submission_open"}, "PURE_SERVICE", False),
        ({"crm_stage": "torgi", "award_status": "submission_closed_waiting_award"}, "DIRECT_GOODS", False),
        ({"crm_stage": "cancelled", "award_status": "cancelled"}, "WORKS_WITH_EMBEDDED_PRODUCTS", False),
        ({"crm_stage": "torgi", "award_status": "submission_open"}, ProcurementScopeType.UNKNOWN.value, False),
    ]
    for procurement, scope, expected in cases:
        admission = evaluate_admission(procurement, scope)
        assert (admission.state == "ELIGIBLE") is expected


def test_gold_override_cannot_resurrect_awarded_direct_goods():
    admission = evaluate_admission(
        {
            "crm_stage": "razygranye",
            "award_status": "awarded",
            "research_prior_band": "GOLD",
            "research_prior_effective_band": "GOLD",
        },
        "DIRECT_GOODS",
    )
    assert admission.state == "EXCLUDED"
    assert not authority_allows_queue({"admission_state": admission.state})


def test_claim_sql_requires_persisted_eligible_context():
    sql = admission_claim_sql("q")
    assert "category_context" in sql
    assert "ELIGIBLE" in sql
    assert "COALESCE" in sql


def test_v4_population_uses_scope_authority_and_current_lifecycle():
    source = (
        Path("src/services/commercial_routing_v3/queue_producer.py")
        .read_text(encoding="utf-8")
    )
    source = source[source.index("    def populate_all_eligible"):source.index("    def upsert")]
    assert "crm_procurement_scope_authority" in source
    assert "admission_state = 'ELIGIBLE'" in source
    assert "submission_open" in source
    assert "razygranye" in source
    assert "AI_QUEUE_ADMISSION_GATE=NO" not in source


def test_document_worker_import_boundary_without_repo_root():
    root = Path(__file__).resolve().parents[1]
    worker_root = root / "tender_documents_research"
    result = subprocess.run(
        [sys.executable, "-c", "from document_processor.admission_policy import admission_claim_sql; print(admission_claim_sql())"],
        cwd=worker_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ELIGIBLE" in result.stdout
