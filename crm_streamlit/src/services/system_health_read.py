"""UI-safe multi-host read path — never probes hardware / never SSH."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.services.system_health_config import (
    COLLECTOR_DOWN_AFTER_SEC,
    HARDWARE_PROBES_ON_UI_RERUN,
    HISTORY_LOADED_ON_OVERVIEW,
    HOST_S13,
    HOST_S7,
    MONITORED_HOSTS,
    PAGE_LABEL,
    S7_SSH_CALLS_ON_UI_RERUN,
    S7_STALE_AFTER_SEC,
    STALE_AFTER_SEC,
    UI_HARDWARE_PROBES,
    UI_REFRESH_SEC,
    state_dir,
)
from src.services.system_health_store import read_history, read_latest, snapshot_status

assert UI_HARDWARE_PROBES == 0
assert HARDWARE_PROBES_ON_UI_RERUN is False
assert S7_SSH_CALLS_ON_UI_RERUN == 0
assert HISTORY_LOADED_ON_OVERVIEW is False


def load_dashboard(
    root: Path | None = None,
    *,
    include_history: bool = False,
    history_host: Optional[str] = None,
    history_hours: float = 1.0,
) -> Dict[str, Any]:
    root = root or state_dir()
    snap = read_latest(root)
    if not snap:
        return {
            "ready": False,
            "status": "COLLECTOR_DOWN",
            "snapshot": None,
            "page_label": PAGE_LABEL,
            "monitored_hosts": list(MONITORED_HOSTS),
            "message": "Нет снимка — collector ещё не создал latest.json",
            "ui_refresh_sec": UI_REFRESH_SEC,
            "history": [],
            "hardware_probes": 0,
            "s7_ssh_calls": 0,
            "history_loaded": False,
        }

    if "hosts" not in snap and snap.get("cpu"):
        snap = {
            "collected_at": snap.get("collected_at"),
            "hosts": {HOST_S13: {**snap, "host_id": HOST_S13, "reachable": True}},
            "S13_OVERALL_STATUS": snap.get("overall_status"),
            "S7_OVERALL_STATUS": "UNREACHABLE",
            "GLOBAL_OVERALL_STATUS": snap.get("overall_status"),
            "overall_status": snap.get("overall_status"),
            "alerts": snap.get("alerts") or [],
            "s13_to_s7_connectivity": "unavailable",
        }

    collected = snap.get("collected_at")
    status = snapshot_status(collected, stale_after=STALE_AFTER_SEC, down_after=COLLECTOR_DOWN_AFTER_SEC)
    age = None
    if collected:
        try:
            ts = datetime.fromisoformat(collected)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds()
        except Exception:
            age = None

    history: list = []
    history_loaded = False
    if include_history:
        history = read_history(history_hours, host_id=history_host, root=root)
        history_loaded = True

    return {
        "ready": True,
        "status": status,
        "snapshot": snap,
        "snapshot_age_sec": age,
        "page_label": PAGE_LABEL,
        "monitored_hosts": list(MONITORED_HOSTS),
        "message": "",
        "ui_refresh_sec": UI_REFRESH_SEC,
        "history": history,
        "history_loaded": history_loaded,
        "hardware_probes": 0,
        "s7_ssh_calls": 0,
    }
