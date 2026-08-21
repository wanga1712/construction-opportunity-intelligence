#!/usr/bin/env python3
"""Contention probes: CRM HTTP, PG SELECT via dotenv, RSS/swap."""
from __future__ import annotations

import json
import os
import statistics
import time
import urllib.request
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
os.chdir(ROOT)
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except Exception:
    pass


def http_samples(n: int = 20) -> dict:
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        with urllib.request.urlopen("http://127.0.0.1:8504/", timeout=30) as resp:
            resp.read(256)
            code = resp.status
        samples.append((time.perf_counter() - t0) * 1000.0)
        if code != 200:
            raise RuntimeError(f"HTTP {code}")
    s = sorted(samples)
    return {
        "p50_ms": round(statistics.median(samples), 1),
        "p95_ms": round(s[max(0, int(n * 0.95) - 1)], 1),
        "max_ms": round(max(samples), 1),
        "NO_STALL_OVER_2S": max(samples) <= 2000,
    }


def pg_samples(n: int = 20) -> dict:
    import psycopg2

    dsn = os.environ.get("CRM_DSN") or os.environ.get("DATABASE_URL")
    if not dsn:
        host = os.environ.get("CRM_DB_HOST", "127.0.0.1")
        db = os.environ.get("CRM_DB_NAME", "crm")
        user = os.environ.get("CRM_DB_USER", "crm_app")
        password = os.environ.get("CRM_DB_PASSWORD") or os.environ.get("PGPASSWORD")
        dsn = f"host={host} dbname={db} user={user}"
        if password:
            dsn += " password=" + password
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        conn = psycopg2.connect(dsn, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        samples.append((time.perf_counter() - t0) * 1000.0)
    s = sorted(samples)
    return {
        "p50": round(s[len(s) // 2], 1),
        "p95": round(s[max(0, int(n * 0.95) - 1)], 1),
        "max": round(s[-1], 1),
        "POSTGRES_P95_UNDER_CONTENTION_ACCEPTABLE": s[max(0, int(n * 0.95) - 1)] <= 200.0,
    }


def main() -> None:
    out = {"http": http_samples()}
    try:
        out["pg"] = pg_samples()
    except Exception as e:
        out["pg"] = {"error": type(e).__name__}
    Path("/tmp/ui_contend_probes.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
