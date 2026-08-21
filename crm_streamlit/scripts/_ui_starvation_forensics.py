#!/usr/bin/env python3
"""1s-resolution host forensics sampler (CPU/mem/swap/PSI + top processes)."""
from __future__ import annotations

import json
import time
from pathlib import Path


def read_psi(name: str) -> dict:
    p = Path(f"/proc/pressure/{name}")
    if not p.exists():
        return {}
    line = p.read_text(encoding="utf-8").splitlines()[0]
    # some avg10=... avg60=... avg300=... total=...
    parts = dict(x.split("=", 1) for x in line.split()[1:])
    return {k: float(v) for k, v in parts.items()}


def meminfo() -> dict:
    d = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        k, v = line.split(":", 1)
        d[k] = int(v.strip().split()[0])
    return d


def loadavg() -> list[float]:
    a, b, c, *_ = Path("/proc/loadavg").read_text(encoding="utf-8").split()
    return [float(a), float(b), float(c)]


def top_procs(limit: int = 8) -> list[dict]:
    rows = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            st = (p / "stat").read_text(encoding="utf-8").split()
            # rss pages
            rss_pages = int((p / "statm").read_text(encoding="utf-8").split()[1])
            rss_mb = rss_pages * 4096 // (1024 * 1024)
            comm = st[1].strip("()")
            utime = int(st[13]) + int(st[14])
            rows.append({"pid": int(p.name), "comm": comm, "rss_mb": rss_mb, "jiffies": utime})
        except Exception:
            continue
    rows.sort(key=lambda r: r["rss_mb"], reverse=True)
    return rows[:limit]


def main() -> None:
    duration = 60
    out_path = Path("/tmp/ui_starvation_forensics.jsonl")
    peaks = {
        "load1": 0.0,
        "mem_available_kb_min": 10**18,
        "swap_used_kb_peak": 0,
        "psi_cpu_some": 0.0,
        "psi_mem_some": 0.0,
        "psi_io_some": 0.0,
    }
    with out_path.open("w", encoding="utf-8") as fh:
        t_end = time.time() + duration
        while time.time() < t_end:
            mi = meminfo()
            psi_c = read_psi("cpu")
            psi_m = read_psi("memory")
            psi_i = read_psi("io")
            la = loadavg()
            row = {
                "ts": time.time(),
                "load": la,
                "mem_available_kb": mi.get("MemAvailable"),
                "swap_used_kb": mi.get("SwapTotal", 0) - mi.get("SwapFree", 0),
                "psi_cpu": psi_c,
                "psi_mem": psi_m,
                "psi_io": psi_i,
                "top_rss": top_procs(),
            }
            fh.write(json.dumps(row) + "\n")
            peaks["load1"] = max(peaks["load1"], la[0])
            peaks["mem_available_kb_min"] = min(
                peaks["mem_available_kb_min"], mi.get("MemAvailable", 0)
            )
            peaks["swap_used_kb_peak"] = max(peaks["swap_used_kb_peak"], row["swap_used_kb"])
            peaks["psi_cpu_some"] = max(peaks["psi_cpu_some"], float(psi_c.get("avg10", 0)))
            peaks["psi_mem_some"] = max(peaks["psi_mem_some"], float(psi_m.get("avg10", 0)))
            peaks["psi_io_some"] = max(peaks["psi_io_some"], float(psi_i.get("avg10", 0)))
            time.sleep(1)
    Path("/tmp/ui_starvation_peaks.json").write_text(json.dumps(peaks, indent=2), encoding="utf-8")
    print("PEAKS=" + json.dumps(peaks))


if __name__ == "__main__":
    main()
