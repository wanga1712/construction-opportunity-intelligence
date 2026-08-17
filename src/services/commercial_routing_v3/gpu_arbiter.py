"""Single-GPU heavy-inference arbitration for Candidate routing + documents.

MAX_CONCURRENT_GPU_INFERENCE_JOBS=1.
Workload classes: ROUTING_FOREGROUND, DOCUMENT_BACKGROUND.
When routing queue > 0, routing wins next free slot; documents may borrow 100% when idle.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

WORKLOAD_ROUTING = "ROUTING_FOREGROUND"
WORKLOAD_DOCUMENT = "DOCUMENT_BACKGROUND"
MAX_CONCURRENT_GPU_INFERENCE_JOBS = 1
ROUTING_GPU_TARGET_SHARE = 0.70
DOCUMENT_GPU_TARGET_SHARE = 0.30

_DEFAULT_STATE = Path(
    os.getenv(
        "CRM_GPU_ARBITER_STATE",
        "/var/lib/crm-v3-canary/gpu_arbiter/state.json",
    )
)
_DEFAULT_LOCK = Path(
    os.getenv(
        "CRM_GPU_ARBITER_LOCK",
        "/var/lib/crm-v3-canary/gpu_arbiter/inference.lock",
    )
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dirs(state_path: Path, lock_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)


def read_state(state_path: Optional[Path] = None) -> Dict[str, Any]:
    path = state_path or _DEFAULT_STATE
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "GPU_CURRENT_WORKLOAD": "IDLE",
        "GPU_QUEUE_ROUTING_DEPTH": 0,
        "GPU_QUEUE_DOCUMENT_DEPTH": 0,
        "ROUTING_GPU_SLOTS": 0,
        "DOCUMENT_GPU_SLOTS": 0,
        "LAST_ROUTING_INFERENCE_AT": None,
        "LAST_DOCUMENT_INFERENCE_AT": None,
        "holder_pid": None,
        "updated_at": None,
    }


def write_state(patch: Dict[str, Any], state_path: Optional[Path] = None) -> Dict[str, Any]:
    path = state_path or _DEFAULT_STATE
    _ensure_dirs(path, _DEFAULT_LOCK)
    cur = read_state(path)
    cur.update(patch)
    cur["updated_at"] = _utcnow()
    cur["ROUTING_GPU_TARGET_SHARE"] = ROUTING_GPU_TARGET_SHARE
    cur["DOCUMENT_GPU_TARGET_SHARE"] = DOCUMENT_GPU_TARGET_SHARE
    cur["MAX_CONCURRENT_GPU_INFERENCE_JOBS"] = MAX_CONCURRENT_GPU_INFERENCE_JOBS
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return cur


def set_queue_depths(*, routing: int, document: int) -> None:
    write_state(
        {
            "GPU_QUEUE_ROUTING_DEPTH": int(routing),
            "GPU_QUEUE_DOCUMENT_DEPTH": int(document),
        }
    )


def should_defer_document(*, routing_depth: Optional[int] = None) -> bool:
    """Documents defer when routing has pending work (foreground priority)."""
    st = read_state()
    depth = routing_depth if routing_depth is not None else int(st.get("GPU_QUEUE_ROUTING_DEPTH") or 0)
    return depth > 0


@contextmanager
def acquire_gpu_inference(
    workload: str,
    *,
    lock_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
    poll_sec: float = 0.5,
    max_wait_sec: float = 3600.0,
    wait_started_at: Optional[float] = None,
) -> Iterator[Dict[str, Any]]:
    """Exclusive file lock for one heavy Ollama/GPU inference job.

    Does not preempt an in-flight holder. Callers wait for the free slot.
    Routing callers should not call should_defer; document callers should
    check should_defer_document() before waiting when policy requires it.
    """
    import fcntl

    path = lock_path or _DEFAULT_LOCK
    spath = state_path or _DEFAULT_STATE
    _ensure_dirs(spath, path)
    wait_t0 = wait_started_at if wait_started_at is not None else time.monotonic()
    fh = open(path, "a+", encoding="utf-8")
    deadline = time.monotonic() + max_wait_sec
    acquired = False
    try:
        while time.monotonic() < deadline:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(poll_sec)
        if not acquired:
            raise TimeoutError(f"gpu arbiter lock timeout workload={workload}")
        wait_sec = max(0.0, time.monotonic() - wait_t0)
        slot_key = (
            "ROUTING_GPU_SLOTS" if workload == WORKLOAD_ROUTING else "DOCUMENT_GPU_SLOTS"
        )
        st = read_state(spath)
        slots = int(st.get(slot_key) or 0) + 1
        patch: Dict[str, Any] = {
            "GPU_CURRENT_WORKLOAD": workload,
            "holder_pid": os.getpid(),
            slot_key: slots,
            "last_wait_sec": round(wait_sec, 3),
        }
        if workload == WORKLOAD_ROUTING:
            patch["LAST_ROUTING_INFERENCE_AT"] = _utcnow()
        else:
            patch["LAST_DOCUMENT_INFERENCE_AT"] = _utcnow()
        write_state(patch, spath)
        yield {"workload": workload, "wait_sec": wait_sec, "state": read_state(spath)}
    finally:
        if acquired:
            write_state({"GPU_CURRENT_WORKLOAD": "IDLE", "holder_pid": None}, spath)
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        fh.close()
