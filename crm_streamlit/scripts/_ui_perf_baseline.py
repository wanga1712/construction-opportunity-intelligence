#!/usr/bin/env python3
"""Baseline timings for CRM UI blocking path (no Streamlit UI)."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases
from src.services.companies_service import CompaniesService
from src.services.db_health import check_and_reconnect
from src.services.system_health_read import load_dashboard


def timed(fn, *a, **k):
    t0 = time.perf_counter()
    out = fn(*a, **k)
    return out, (time.perf_counter() - t0) * 1000.0


def main():
    results = {"CONNECT_DATABASES_MS": [], "COMPANIES_LOAD_SYNC_MS": [], "DB_HEALTH_MS": [], "LOAD_DASHBOARD_MS": []}

    for i in range(5):
        (radar, tender, crm, warn), ms = timed(connect_databases)
        results["CONNECT_DATABASES_MS"].append(round(ms, 1))
        if i == 0:
            service = CompaniesService(radar_db=radar, tender_db=tender, crm_db=crm)
            ok, ms_load = timed(service.load_sync)
            results["COMPANIES_LOAD_SYNC_MS"].append(round(ms_load, 1))
            results["LOAD_SYNC_OK"] = ok
        else:
            # reuse service for health pings
            pass
        if i == 0:
            svc = service
        _, ms_h = timed(check_and_reconnect, svc, previously_online=True)
        results["DB_HEALTH_MS"].append(round(ms_h, 1))
        _, ms_d = timed(load_dashboard)
        results["LOAD_DASHBOARD_MS"].append(round(ms_d, 1))
        print(f"iter={i} connect={results['CONNECT_DATABASES_MS'][-1]} health={results['DB_HEALTH_MS'][-1]} dash={results['LOAD_DASHBOARD_MS'][-1]}")

    summary = {
        k: {
            "samples": v,
            "p50": round(statistics.median(v), 1) if v else None,
            "p95": round(sorted(v)[max(0, int(len(v) * 0.95) - 1)], 1) if v else None,
            "mean": round(statistics.mean(v), 1) if v else None,
        }
        for k, v in results.items()
        if isinstance(v, list)
    }
    summary["LOAD_SYNC_OK"] = results.get("LOAD_SYNC_OK")
    summary["COMPANIES_LOAD_SYNC_MS_SINGLE"] = results["COMPANIES_LOAD_SYNC_MS"]
    summary["BLOCKING_PATH"] = (
        "render_sidebar_nav → _get_service → page; "
        "system_health always waits CompaniesService"
    )
    summary["SYSTEM_HEALTH_REQUIRES_COMPANIES_SERVICE_BEFORE"] = "YES"
    summary["SYSTEM_HEALTH_REQUIRES_RADAR_BEFORE"] = "YES"
    summary["DB_HEALTH_CHECKS_PER_NAV_RERUN"] = 2  # watchdog + _get_service when service exists
    Path("/tmp/ui_nav_baseline.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SUMMARY=" + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
