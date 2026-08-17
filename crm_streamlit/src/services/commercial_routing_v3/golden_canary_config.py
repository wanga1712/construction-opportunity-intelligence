"""Paths and invariants for V3 golden canary (boot one-shot)."""
from __future__ import annotations

from pathlib import Path

CANARY_ID = "golden_canary_20260813"
CANARY_DIR = Path("/var/lib/crm-v3-canary")
MARKER_PATH = CANARY_DIR / f"{CANARY_ID}.done"
REPORT_PATH = CANARY_DIR / f"{CANARY_ID}.json"
STATUS_PATH = CANARY_DIR / "status.json"
REFERENCE_PATH = CANARY_DIR / f"{CANARY_ID}.reference.json"

MAX_PROCUREMENTS_PROCESSED = 4
READINESS_INITIAL_DELAY_SEC = 45
READINESS_RETRY_INTERVAL_SEC = 10
READINESS_MAX_WAIT_SEC = 300  # 5 minutes total window after initial delay

PRODUCTION_PROJECTION_WRITER_REQUIRED = "V3"

# Hard freezes during canary
FROZEN_AI_UNITS = (
    "crm-ai-assessment-runner.timer",
    "crm-ai-assessment-runner.service",
    "crm-ai-precompute.timer",
)
FROZEN_DOC_UNITS = (
    "tender-docs-daemon-open.service",
    "tender-docs-daemon-awarded.service",
    "tender-docs-shadow-runner.timer",
    "tender-docs-shadow-runner.service",
)

QUEUE_GENERATED = False  # invariant: canary never enqueues docs
DOCUMENT_PROCESSING_RUN = False
BATCH_ROUTING_TRIGGERED = False
CANARY_RUN_MAX_ONCE = True

STATUS_ARMED = "ARMED"
STATUS_WAITING = "WAITING_FOR_NEXT_BOOT"
STATUS_RUNNING = "RUNNING"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIPPED = "CANARY_ALREADY_EXECUTED"
