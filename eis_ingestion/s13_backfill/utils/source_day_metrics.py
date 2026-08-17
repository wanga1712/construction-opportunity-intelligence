"""Cheap JSONL wall-time metrics for one EIS source-date.

One line per region / source-date event. Not per-object.
Path: TENDERMONITOR_METRICS_FILE or <repo>/source_day_metrics.jsonl
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def metrics_path() -> Path:
    raw = os.getenv("TENDERMONITOR_METRICS_FILE")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent.parent / "source_day_metrics.jsonl"


def emit(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        **fields,
    }
    try:
        path = metrics_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        return
