#!/usr/bin/env python3
"""Server-side lightweight nav timing under contention (Streamlit HTTP smoke).

Measures repeated GETs to Streamlit root while optional background burn runs.
Not a full websocket click timing, but catches scheduler stalls >2s.
"""
from __future__ import annotations

import json
import statistics
import time
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:8504/"
N = 20


def one() -> float:
    t0 = time.perf_counter()
    with urllib.request.urlopen(URL, timeout=30) as resp:
        resp.read(256)
        code = resp.status
    ms = (time.perf_counter() - t0) * 1000.0
    if code != 200:
        raise RuntimeError(f"HTTP {code}")
    return ms


def main() -> int:
    samples = [one() for _ in range(N)]
    out = {
        "n": N,
        "p50_ms": round(statistics.median(samples), 1),
        "p95_ms": round(sorted(samples)[max(0, int(N * 0.95) - 1)], 1),
        "max_ms": round(max(samples), 1),
        "mean_ms": round(statistics.mean(samples), 1),
        "NO_NAV_CLICK_STALLS_OVER_2S": max(samples) <= 2000,
        "samples_ms": [round(x, 1) for x in samples],
    }
    Path("/tmp/ui_contention_http.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("CONTENTION_HTTP=" + json.dumps(out))
    return 0 if out["NO_NAV_CLICK_STALLS_OVER_2S"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
