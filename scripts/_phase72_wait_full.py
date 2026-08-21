#!/usr/bin/env python3
"""Poll Phase 7.2 full bake-off until done; print progress."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

LOG = Path("/tmp/phase72_t_lite_full.log")
OUT = Path("/tmp/phase72_t_lite_full.json")
UNIT = "crm-phase72-t-lite-full.service"


def active() -> str:
    return subprocess.check_output(["systemctl", "is-active", UNIT], text=True).strip()


def last_i() -> int | None:
    if not LOG.exists():
        return None
    best = None
    for line in LOG.read_text(errors="replace").splitlines():
        if '"i":' in line and line.strip().startswith("{"):
            try:
                best = int(json.loads(line)["i"])
            except Exception:
                m = re.search(r'"i":\s*(\d+)', line)
                if m:
                    best = int(m.group(1))
    return best


def main() -> None:
    while True:
        st = active()
        i = last_i()
        print(f"state={st} last_i={i} out_exists={OUT.exists()}", flush=True)
        if st != "active":
            break
        if OUT.exists() and "SUMMARY=" in LOG.read_text(errors="replace"):
            break
        time.sleep(60)
    if OUT.exists():
        d = json.loads(OUT.read_text(encoding="utf-8"))
        print(
            "DONE",
            {
                "MODE": d.get("MODE"),
                "t_lite": d.get("t_lite_v6_1"),
                "qwen": d.get("qwen_v6_1"),
                "mut_a": d.get("PRODUCTION_ASSESSMENTS_MUTATED"),
                "mut_o": d.get("PRODUCTION_OPPORTUNITIES_MUTATED"),
            },
        )
    else:
        print("NO_OUT")
        print(LOG.read_text(errors="replace")[-2000:])


if __name__ == "__main__":
    main()
