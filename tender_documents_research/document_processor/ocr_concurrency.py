"""Cross-process OCR concurrency guard.

Document workers run as separate systemd services. A process-local semaphore
would still allow every worker to launch tesseract, so this module uses
non-blocking file locks to cap OCR work globally.
"""
from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_MAX_CONCURRENCY = 4
LOCK_DIR = Path(os.getenv("OCR_LOCK_DIR", "/tmp/tender-docs-ocr-slots"))


def ocr_max_concurrency() -> int:
    try:
        configured = int(os.getenv("OCR_MAX_CONCURRENCY", str(DEFAULT_MAX_CONCURRENCY)))
    except ValueError:
        configured = DEFAULT_MAX_CONCURRENCY
    return max(2, min(4, configured))


@contextmanager
def ocr_slot() -> Iterator[None]:
    """Block until one of the global OCR slots is available."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        for index in range(ocr_max_concurrency()):
            handle = (LOCK_DIR / f"slot-{index}.lock").open("a+")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                continue
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
            return
        time.sleep(0.2)
