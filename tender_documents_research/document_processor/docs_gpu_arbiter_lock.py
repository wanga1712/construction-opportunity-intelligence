"""Standalone GPU inference lock for tender_documents_research (no CRM imports).

Shares the same lock path as CRM gpu_arbiter so MAX_CONCURRENT_GPU_INFERENCE_JOBS=1.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator

LOCK_PATH = Path(
    os.getenv(
        "CRM_GPU_ARBITER_LOCK",
        "/var/lib/crm-v3-canary/gpu_arbiter/inference.lock",
    )
)
STATE_PATH = Path(
    os.getenv(
        "CRM_GPU_ARBITER_STATE",
        "/var/lib/crm-v3-canary/gpu_arbiter/state.json",
    )
)
WORKLOAD_DOCUMENT = "DOCUMENT_BACKGROUND"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state() -> Dict[str, Any]:
    try:
        if STATE_PATH.is_file():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"GPU_QUEUE_ROUTING_DEPTH": 0, "GPU_CURRENT_WORKLOAD": "IDLE"}


def _write_state(patch: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cur = _read_state()
    cur.update(patch)
    cur["updated_at"] = _utcnow()
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def routing_queue_busy() -> bool:
    return int(_read_state().get("GPU_QUEUE_ROUTING_DEPTH") or 0) > 0


@contextmanager
def acquire_document_gpu(
    *,
    poll_sec: float = 0.5,
    max_wait_sec: float = 3600.0,
    defer_when_routing: bool = True,
) -> Iterator[Dict[str, Any]]:
    import fcntl

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    wait_t0 = time.monotonic()
    # Soft defer: wait until routing depth is 0 (do not kill in-flight routing).
    if defer_when_routing:
        while routing_queue_busy() and (time.monotonic() - wait_t0) < max_wait_sec:
            time.sleep(poll_sec)

    fh = open(LOCK_PATH, "a+", encoding="utf-8")
    deadline = time.monotonic() + max_wait_sec
    acquired = False
    try:
        while time.monotonic() < deadline:
            # Re-check routing depth before each lock attempt.
            if defer_when_routing and routing_queue_busy():
                time.sleep(poll_sec)
                continue
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(poll_sec)
        if not acquired:
            raise TimeoutError("document gpu arbiter timeout")
        wait_sec = max(0.0, time.monotonic() - wait_t0)
        st = _read_state()
        slots = int(st.get("DOCUMENT_GPU_SLOTS") or 0) + 1
        _write_state(
            {
                "GPU_CURRENT_WORKLOAD": WORKLOAD_DOCUMENT,
                "holder_pid": os.getpid(),
                "DOCUMENT_GPU_SLOTS": slots,
                "LAST_DOCUMENT_INFERENCE_AT": _utcnow(),
                "last_wait_sec": round(wait_sec, 3),
            }
        )
        yield {"wait_sec": wait_sec}
    finally:
        if acquired:
            _write_state({"GPU_CURRENT_WORKLOAD": "IDLE", "holder_pid": None})
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        fh.close()
