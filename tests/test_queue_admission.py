import inspect
import subprocess
import sys
from pathlib import Path

from tender_documents_research.document_processor.admission_policy import (
    ADMISSION_POLICY_VERSION,
    admission_claim_sql,
    authority_allows_queue,
    queue_context_allows_claim,
)
from tender_documents_research.document_processor.admission_reconciliation import (
    MAX_ADMISSION_STALENESS_BEFORE_CLAIM,
    reconcile_active_queue_rows,
)
from tender_documents_research.document_processor.dwrr_claim_policy import (
    DWRRClaimPolicy,
    pool_size,
)
from tender_documents_research.document_processor.research_dedup import (
    canonical_research_identity,
    research_disposition,
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
    assert ADMISSION_POLICY_VERSION in sql
    assert "admission_evaluated_at" in sql


def test_document_dsn_has_no_crm_credential_fallback():
    source = Path("src/services/commercial_routing_v3/queue_producer.py").read_text(encoding="utf-8")
    dsn_source = source[source.index("def _document_dsn_from_env"):source.index("\ndef _load_doc_env")]
    assert '"dbname": "document_intelligence"' in dsn_source
    assert 'os.getenv("S13_DOCUMENT_DB_USER")' in dsn_source
    assert 'os.getenv("S13_DOCUMENT_DB_PASSWORD")' in dsn_source
    assert "CRM_DB_USER" not in dsn_source
    assert "CRM_DB_PASSWORD" not in dsn_source


def test_dwrr_runtime_policy_is_dependency_light_and_weighted():
    rows = [
        {"id": 1, "research_prior_band": "GOLD", "research_prior_score": 90},
        {"id": 2, "research_prior_band": "SILVER", "research_prior_score": 80},
        {"id": 3, "research_prior_band": "BRONZE", "research_prior_score": 70},
        {"id": 4, "research_prior_band": "WOOD", "research_prior_score": 60},
    ]
    assert pool_size(1) == 50
    selected = DWRRClaimPolicy(enabled=True).select_from_pool(rows, 4)
    assert len(selected) == 4
    assert set(selected) == {1, 2, 3, 4}


def test_active_reconciliation_handles_exclude_hold_and_reeligibility():
    base = {
        "admission_state": "ELIGIBLE",
        "admission_reason": "CURRENT_BUSINESS_ADMISSION",
        "admission_policy_version": ADMISSION_POLICY_VERSION,
        "admission_evaluated_at": "2026-09-07T00:00:00+00:00",
        "authority_scope_version": "1.1",
    }
    rows = [
        {"id": 1, "procurement_id": 101, "status": "PENDING", "category_context": base},
        {"id": 2, "procurement_id": 102, "status": "PRE_RESEARCH_WAITING", "category_context": base},
        {"id": 3, "procurement_id": 103, "status": "COMPLETED", "category_context": base},
    ]
    authorities = {
        101: {"admission_state": "EXCLUDED", "admission_reason": "AWARDED_DIRECT_GOODS", "admission_evaluated_at": "new", "scope_version": "1.1"},
        102: {"admission_state": "HOLD", "admission_reason": "UNKNOWN_SCOPE", "admission_evaluated_at": "new", "scope_version": "1.1"},
        103: {"admission_state": "ELIGIBLE", "admission_reason": "CURRENT_BUSINESS_ADMISSION", "admission_evaluated_at": "new", "scope_version": "1.1"},
    }
    changes = reconcile_active_queue_rows(rows, authorities)
    assert {change["admission_state"] for change in changes} == {"EXCLUDED", "HOLD"}
    assert all(change["queue_id"] != 3 for change in changes)
    assert MAX_ADMISSION_STALENESS_BEFORE_CLAIM == "reconciled immediately before every claim cycle"


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


def test_research_identity_is_notice_scoped_to_source_family():
    first = canonical_research_identity(
        source_family="reestr_contract_44_fz",
        notice_number="N-100",
        procurement_id=1,
    )
    lifecycle_duplicate = canonical_research_identity(
        source_family="reestr_contract_44_fz",
        notice_number="N-100",
        procurement_id=2,
    )
    other_family = canonical_research_identity(
        source_family="reestr_contract_223_fz",
        notice_number="N-100",
        procurement_id=3,
    )
    assert first.key == lifecycle_duplicate.key
    assert first.key != other_family.key


def test_research_disposition_preserves_existing_research_precedence():
    assert research_disposition([{"status": "PROCESSING"}]) == "DO_NOT_ENQUEUE_DUPLICATE_PROCESSING"
    assert research_disposition([{"status": "PENDING"}]) == "DO_NOT_ENQUEUE_DUPLICATE_PENDING"
    assert research_disposition([{"status": "COMPLETED", "successful_parse": True}]) == "REUSE_EXISTING_RESEARCH"
    assert research_disposition([{"status": "COMPLETED", "successful_parse": False}]) == "RETRY_EXISTING_IDENTITY"
    assert research_disposition([{"status": "FAILED"}]) == "RETRY_EXISTING_IDENTITY"
    assert research_disposition([{"status": "FAILED"}, {"status": "PENDING"}]) == "DO_NOT_ENQUEUE_DUPLICATE_PENDING"


def test_research_dedup_is_not_generation_only():
    source = Path("src/services/commercial_routing_v3/queue_producer.py").read_text(encoding="utf-8")
    producer = source[source.index("    def _upsert_queue_task"):]
    assert "q.source_table = %s" in producer
    assert "q.contract_number = %s" in producer
    assert "document_processing_results" in producer
    assert "pipeline_generation = %s" not in producer
