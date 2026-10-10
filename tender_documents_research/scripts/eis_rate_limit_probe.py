#!/usr/bin/env python3
"""One-shot EIS recovery probe. Safe to run from a timer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(dotenv_path=ROOT / ".env")
load_dotenv(dotenv_path=ROOT / "database_work" / "db_credintials.env")

from document_processor.eis_recovery_probe import run_recovery_probe  # noqa: E402
from document_processor.eis_rate_limit_guard import get_eis_guard  # noqa: E402


def main() -> int:
    guard = get_eis_guard()
    result = run_recovery_probe(guard=guard)
    print(f"EIS_PROBE_STATUS={result.get('status')}")
    print(guard.operational_report())
    if os.getenv("EIS_PROBE_STRICT") == "1" and result.get("status") not in (
        "RECOVERED",
        "NOT_DUE",
        "LOCK_BUSY",
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
