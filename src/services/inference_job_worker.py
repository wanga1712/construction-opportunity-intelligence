"""Bounded queue worker adapter over the existing production inference runner."""
from __future__ import annotations

import socket
from typing import Any

from src.services.crm_ai_assessment_runner import run_live
from src.services.inference_job_queue import (
    claim_next_jobs, heartbeat, mark_cancelled, mark_failed, mark_succeeded, recover_stale_jobs,
)
from src.services.commercial_routing_v3.submission_window import (
    TOO_SHORT_REASON, is_actionable_submission_window,
)


def execute_claimed_job(job: dict, *, tender_db: Any, crm_db: Any, worker_id: str) -> dict:
    """Execute one claimed job through run_live; never constructs prompt/input itself."""
    job_id = int(job["id"]); procurement_id = int(job["procurement_id"])
    heartbeat(crm_db, job_id, worker_id)
    try:
        rows = crm_db.execute_query("SELECT crm_stage,end_date FROM crm_procurements WHERE id=%s", (procurement_id,)) or []
        proc = rows[0] if rows else {}
        if str(proc.get("crm_stage") or "").lower() == "torgi" and not is_actionable_submission_window(proc.get("end_date")):
            mark_cancelled(crm_db, job_id, worker_id, TOO_SHORT_REASON)
            return {"job_id": job_id, "status": "CANCELLED", "reason": TOO_SHORT_REASON}
        outcome = run_live(
            tender_db, crm_db, limit=1, procurement_id=procurement_id,
            force_reassess=True, reassess_reason=f"durable_job:{job_id}",
        )
        rows = crm_db.execute_query(
            """SELECT inference_run_id,status FROM procurement_ai_assessments
               WHERE procurement_id=%s AND is_current ORDER BY id DESC LIMIT 1""",
            (procurement_id,)) or []
        run_id = rows[0].get("inference_run_id") if rows else None
        if int(outcome.get("success") or 0) != 1 or not run_id:
            raise RuntimeError(f"INFERENCE_OR_ASSESSMENT_NOT_COMMITTED:{outcome}")
        if not mark_succeeded(crm_db, job_id, worker_id, int(run_id)):
            raise RuntimeError("JOB_COMPLETION_RECONCILIATION_REQUIRED")
        return {"job_id": job_id, "status": "SUCCEEDED", "inference_run_id": int(run_id)}
    except Exception as exc:
        mark_failed(crm_db, job_id, worker_id, str(exc))
        return {"job_id": job_id, "status": "FAILED", "error": str(exc)}


def run_worker_once(*, tender_db: Any, crm_db: Any, limit: int = 1,
                    worker_id: str | None = None) -> list[dict]:
    worker_id = worker_id or f"{socket.gethostname()}:{__import__('os').getpid()}"
    recover_stale_jobs(crm_db)
    jobs = claim_next_jobs(crm_db, claimed_by=worker_id, limit=limit)
    return [execute_claimed_job(job, tender_db=tender_db, crm_db=crm_db, worker_id=worker_id)
            for job in jobs]
