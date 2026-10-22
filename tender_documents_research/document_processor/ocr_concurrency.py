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
    base = max(2, min(4, configured))
    if os.getenv("OCR_BACKPRESSURE_ENABLED", "1") not in ("1", "true", "yes", "on"):
        return base
    try:
        load_1m = os.getloadavg()[0]
        cpu_count = max(1, os.cpu_count() or 1)
        high_watermark = float(os.getenv("OCR_CPU_HIGH_WATERMARK", "0.9"))
        if load_1m / cpu_count >= high_watermark:
            try:
                floor = int(os.getenv("OCR_BACKPRESSURE_MIN_CONCURRENCY", "2"))
            except ValueError:
                floor = 2
            return max(2, min(base, floor))
    except (AttributeError, OSError, ValueError):
        pass
    return base


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
