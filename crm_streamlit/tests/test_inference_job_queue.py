from pathlib import Path

from src.services import inference_job_queue as queue
from src.services import inference_job_worker as worker


def test_migration_has_active_partial_unique_and_skip_locked():
    sql = (Path(__file__).parents[1] / "src/migrations/crm_v3_inference_jobs.sql").read_text()
    assert "WHERE status IN ('QUEUED','RUNNING')" in sql
    assert "UNIQUE INDEX" in sql
    assert "retry_of_job_id" in sql
    source = Path(queue.__file__).read_text()
    assert "FOR UPDATE SKIP LOCKED" in source


def test_input_identity_uses_existing_controlled_builder(monkeypatch):
    monkeypatch.setattr(queue, "fetch_procurement_for_controlled_reassess", lambda db, pid: {
        "v3_model_input": {"model_input_version": "V3", "title": "x"}
    })
    first = queue.canonical_input_identity(object(), 1)
    second = queue.canonical_input_identity(object(), 1)
    assert first["result"] == "READY"
    assert first["input_fingerprint"] == second["input_fingerprint"]
    assert len(first["input_fingerprint"]) == 64


def test_input_identity_rejects_ineligible(monkeypatch):
    monkeypatch.setattr(queue, "fetch_procurement_for_controlled_reassess", lambda db, pid: {
        "eligibility_blocked": "SOURCE_INVALID"
    })
    assert queue.canonical_input_identity(object(), 1)["result"] == "NOT_MODEL_ELIGIBLE"


def test_worker_delegates_to_existing_run_live(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "heartbeat", lambda *a: True)
    monkeypatch.setattr(worker, "run_live", lambda *a, **kw: calls.append(kw) or {"success": 1})
    monkeypatch.setattr(worker, "mark_succeeded", lambda *a: True)
    class Db:
        def execute_query(self, *a, **k): return [{"inference_run_id": 99, "status": "SUCCESS"}]
    out = worker.execute_claimed_job({"id": 7, "procurement_id": 3}, tender_db=object(), crm_db=Db(), worker_id="w")
    assert out["status"] == "SUCCEEDED"
    assert calls[0]["force_reassess"] is True
    assert calls[0]["procurement_id"] == 3


def test_expert_storage_is_not_read_by_queue_or_worker():
    text = Path(queue.__file__).read_text() + Path(worker.__file__).read_text()
    assert "crm_v3_expert_annotations" not in text
    assert "load_expert_annotation" not in text


def test_stale_timeout_is_conservative():
    assert queue.STALE_AFTER.total_seconds() == 1800
