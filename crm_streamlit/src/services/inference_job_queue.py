"""Durable authority for AI inference jobs; never calls the model on enqueue."""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Iterable

from psycopg2 import errors

from src.services.crm_ai_assessment_runner import (
    CURRENT_MODEL,
    fetch_procurement_for_controlled_reassess,
)
from src.services.commercial_routing_v3.prompt import PROMPT_VERSION

RUN_KIND_PRODUCTION = "PRODUCTION"
ACTIVE = ("QUEUED", "RUNNING")
STALE_AFTER = timedelta(minutes=30)


@contextmanager
def _transaction(crm_db: Any):
    acquired = hasattr(crm_db, "get_connection")
    if acquired:
        conn = crm_db.get_connection()
    else:
        crm_db._ensure_connection(); conn = crm_db._connection
    try:
        with conn:
            yield conn
    finally:
        if acquired:
            crm_db.release_connection(conn)


def canonical_input_identity(crm_db: Any, procurement_id: int) -> dict:
    """Use the existing production builder; expert annotations are never read."""
    item = fetch_procurement_for_controlled_reassess(crm_db, procurement_id)
    if not item or item.get("eligibility_blocked"):
        return {"result": "NOT_MODEL_ELIGIBLE", "reason": (item or {}).get("eligibility_blocked")}
    model_input = item.get("v3_model_input")
    if not isinstance(model_input, dict):
        return {"result": "ERROR", "reason": "CANONICAL_MODEL_INPUT_MISSING"}
    encoded = json.dumps(model_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "result": "READY", "model_input": model_input,
        "input_fingerprint": hashlib.sha256(encoded.encode()).hexdigest(),
        "model_version": CURRENT_MODEL, "prompt_version": PROMPT_VERSION,
    }


def enqueue_inference_job(
    crm_db: Any, procurement_id: int, *, requested_by: str,
    request_source: str, run_kind: str = RUN_KIND_PRODUCTION,
    retry_of_job_id: int | None = None,
) -> dict:
    identity = canonical_input_identity(crm_db, procurement_id)
    if identity["result"] != "READY":
        return identity
    key = (procurement_id, identity["model_version"], identity["prompt_version"], run_kind, identity["input_fingerprint"])
    try:
        with _transaction(crm_db) as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO crm_v3_inference_jobs
                   (procurement_id,model_version,prompt_version,run_kind,input_fingerprint,
                    requested_by,request_source,retry_of_job_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,status""",
                (*key, requested_by, request_source, retry_of_job_id),
            )
            job_id, status = cur.fetchone()
        return {"result": "CREATED", "job_id": job_id, "status": status, **identity}
    except errors.UniqueViolation:
        rows = crm_db.execute_query(
            """SELECT id,status FROM crm_v3_inference_jobs
               WHERE procurement_id=%s AND model_version=%s AND prompt_version=%s
                 AND run_kind=%s AND input_fingerprint=%s AND status=ANY(%s)
               ORDER BY id DESC LIMIT 1""", (*key, list(ACTIVE))) or []
        row = rows[0]
        return {"result": "ALREADY_ACTIVE", "job_id": row["id"], "status": row["status"], **identity}


def claim_next_jobs(crm_db: Any, *, claimed_by: str, limit: int = 1) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    with _transaction(crm_db) as conn, conn.cursor() as cur:
        cur.execute(
            """WITH picked AS (
                 SELECT id FROM crm_v3_inference_jobs
                  WHERE status='QUEUED' AND available_at<=NOW()
                  ORDER BY available_at,created_at,id FOR UPDATE SKIP LOCKED LIMIT %s
               )
               UPDATE crm_v3_inference_jobs j SET status='RUNNING',claimed_by=%s,
                 started_at=coalesce(started_at,NOW()),heartbeat_at=NOW(),attempt_count=attempt_count+1
               FROM picked WHERE j.id=picked.id RETURNING j.*""", (limit, claimed_by))
        names = [d.name for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def heartbeat(crm_db: Any, job_id: int, claimed_by: str) -> bool:
    return bool(crm_db.execute_update(
        "UPDATE crm_v3_inference_jobs SET heartbeat_at=NOW() WHERE id=%s AND status='RUNNING' AND claimed_by=%s",
        (job_id, claimed_by)))


def mark_succeeded(crm_db: Any, job_id: int, claimed_by: str, inference_run_id: int) -> bool:
    return bool(crm_db.execute_update(
        """UPDATE crm_v3_inference_jobs SET status='SUCCEEDED',inference_run_id=%s,
           finished_at=NOW(),heartbeat_at=NOW() WHERE id=%s AND status='RUNNING' AND claimed_by=%s""",
        (inference_run_id, job_id, claimed_by)))


def mark_failed(crm_db: Any, job_id: int, claimed_by: str, error: str) -> bool:
    return bool(crm_db.execute_update(
        """UPDATE crm_v3_inference_jobs SET status='FAILED',last_error=%s,finished_at=NOW(),
           heartbeat_at=NOW() WHERE id=%s AND status='RUNNING' AND claimed_by=%s""",
        (str(error)[:4000], job_id, claimed_by)))


def mark_cancelled(crm_db: Any, job_id: int, claimed_by: str, reason: str) -> bool:
    return bool(crm_db.execute_update(
        """UPDATE crm_v3_inference_jobs SET status='CANCELLED',last_error=%s,finished_at=NOW(),
           heartbeat_at=NOW() WHERE id=%s AND status='RUNNING' AND claimed_by=%s""",
        (str(reason)[:4000], job_id, claimed_by)))


def recover_stale_jobs(crm_db: Any, *, stale_after: timedelta = STALE_AFTER) -> dict:
    seconds = max(60, int(stale_after.total_seconds()))
    with _transaction(crm_db) as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE crm_v3_inference_jobs SET
                 status=CASE WHEN attempt_count<max_attempts THEN 'QUEUED' ELSE 'FAILED' END,
                 available_at=CASE WHEN attempt_count<max_attempts THEN NOW() ELSE available_at END,
                 finished_at=CASE WHEN attempt_count>=max_attempts THEN NOW() ELSE NULL END,
                 claimed_by=NULL,last_error='STALE_WORKER_LEASE'
               WHERE status='RUNNING' AND coalesce(heartbeat_at,started_at,created_at)
                 < NOW()-(%s*INTERVAL '1 second') RETURNING status""", (seconds,))
        statuses = [row[0] for row in cur.fetchall()]
    return {"requeued": statuses.count("QUEUED"), "failed": statuses.count("FAILED")}


def bulk_enqueue(crm_db: Any, procurement_ids: Iterable[int], *, requested_by: str,
                 request_source: str, dry_run: bool = True) -> dict:
    result = {"eligible": 0, "already_assessed": 0, "already_active": 0,
              "not_model_expected": 0, "would_enqueue": 0, "created": 0}
    for procurement_id in dict.fromkeys(int(x) for x in procurement_ids):
        current = crm_db.execute_scalar(
            "SELECT EXISTS(SELECT 1 FROM procurement_ai_assessments WHERE procurement_id=%s AND is_current AND status='SUCCESS')",
            (procurement_id,))
        if current:
            result["already_assessed"] += 1; continue
        identity = canonical_input_identity(crm_db, procurement_id)
        if identity["result"] != "READY":
            result["not_model_expected"] += 1; continue
        result["eligible"] += 1
        active = crm_db.execute_scalar(
            """SELECT EXISTS(SELECT 1 FROM crm_v3_inference_jobs WHERE procurement_id=%s
               AND model_version=%s AND prompt_version=%s AND run_kind=%s
               AND input_fingerprint=%s AND status=ANY(%s))""",
            (procurement_id, identity["model_version"], identity["prompt_version"],
             RUN_KIND_PRODUCTION, identity["input_fingerprint"], list(ACTIVE)))
        if active:
            result["already_active"] += 1; continue
        result["would_enqueue"] += 1
        if not dry_run:
            made = enqueue_inference_job(crm_db, procurement_id, requested_by=requested_by,
                                         request_source=request_source)
            result["created"] += made["result"] == "CREATED"
    return result
