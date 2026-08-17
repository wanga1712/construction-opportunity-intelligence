#!/usr/bin/env python3
"""Phase 1: freeze S7 forward runtime snapshot. Read-only. No secrets."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path("/opt/tendermonitor")
OUT = Path("/tmp/eis_s7_correctness")
SERVICE = "tendermonitor-eis-parser.service"
BACKWARD = "tendermonitor-eis-parser-backward.service"


def show(unit: str) -> dict:
    raw = subprocess.check_output(
        [
            "systemctl",
            "show",
            unit,
            "-p",
            "Id,ActiveState,SubState,MainPID,NRestarts,ActiveEnterTimestamp,FragmentPath,User,WorkingDirectory",
            "--no-pager",
        ],
        text=True,
    )
    data = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    return data


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    rp = {}
    rp_path = ROOT / "region_progress.json"
    if rp_path.exists():
        rp = json.loads(rp_path.read_text(encoding="utf-8"))
    counts = {}
    for date, payload in rp.items():
        regs = payload.get("processed_regions", payload) if isinstance(payload, dict) else payload
        counts[date] = len(regs) if regs is not None else 0
    cfg_lines = []
    cfg = ROOT / "config.ini"
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("date") or stripped.startswith("start"):
                cfg_lines.append(stripped)
    out = {
        "ts": now,
        "host": os.uname().nodename if hasattr(os, "uname") else None,
        "S7_FORWARD_SERVICE": SERVICE,
        "SERVICE_ACTIVE": show(SERVICE),
        "BACKWARD_SERVICE": show(BACKWARD),
        "CURRENT_REGION_PROGRESS_COUNTS": counts,
        "CURRENT_REGION_PROGRESS_KEYS": sorted(rp.keys()),
        "config_date_lines": cfg_lines,
        "QWEN_STARTED": "NO",
        "NOTE": "Do not restart S7 unless a proven critical data-loss bug is found.",
    }
    path = OUT / "phase1_freeze.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
