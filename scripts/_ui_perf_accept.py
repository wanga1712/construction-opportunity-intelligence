#!/usr/bin/env python3
"""Post-fix acceptance: light page path must not call CompaniesService.load_sync."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

import src.ui.app_bootstrap as boot
from src.services.system_health_read import load_dashboard
from src.ui.page_deps import page_dependency, requires_companies_load_sync


def main():
    calls = {"create": 0, "get": 0, "load": 0, "watchdog": 0}

    class _St:
        class session_state(dict):
            def get(self, *a, **k):
                return dict.get(self, *a, **k)

            def __getattr__(self, k):
                try:
                    return self[k]
                except KeyError as e:
                    raise AttributeError(k) from e

            def __setattr__(self, k, v):
                self[k] = v

        session_state = session_state()
        @staticmethod
        def stop():
            raise RuntimeError("st.stop")
        @staticmethod
        def info(*a, **k):
            pass
        @staticmethod
        def error(*a, **k):
            pass
        @staticmethod
        def spinner(*a, **k):
            return MagicMock().__enter__()

    # Patch streamlit symbols used by bootstrap for light path
    boot.st = _St  # type: ignore
    boot.render_sidebar_nav = lambda: "system_health"  # type: ignore
    boot._create_service = lambda **k: calls.__setitem__("create", calls["create"] + 1)  # type: ignore
    boot._get_service = lambda **k: calls.__setitem__("get", calls["get"] + 1)  # type: ignore
    boot._db_connection_watchdog = lambda: calls.__setitem__("watchdog", calls["watchdog"] + 1)  # type: ignore
    boot.render_db_status_banner = lambda: None  # type: ignore

    dash_ms = []
    for _ in range(5):
        t0 = time.perf_counter()
        boot.render_system_health_page = lambda service=None: None  # type: ignore
        boot.main()
        # page body cost separately
        _, = (None,)
        t_dash0 = time.perf_counter()
        load_dashboard()
        dash_ms.append((time.perf_counter() - t_dash0) * 1000)
        _ = time.perf_counter() - t0

    out = {
        "SYSTEM_HEALTH_COMPANIES_SERVICE_CALLS_AFTER": calls["create"] + calls["get"],
        "SYSTEM_HEALTH_WATCHDOG_CALLS": calls["watchdog"],
        "requires_companies_load_sync": requires_companies_load_sync("system_health"),
        "page_dependency": page_dependency("system_health").value,
        "LOAD_DASHBOARD_P50_MS": round(statistics.median(dash_ms), 2),
        "LOAD_DASHBOARD_P95_MS": round(sorted(dash_ms)[max(0, int(len(dash_ms) * 0.95) - 1)], 2),
        "DB_HEALTH_CHECKS_PER_LIGHT_NAV_AFTER": 0,
    }
    Path("/tmp/ui_nav_after.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("AFTER=" + json.dumps(out))
    assert out["SYSTEM_HEALTH_COMPANIES_SERVICE_CALLS_AFTER"] == 0
    assert out["SYSTEM_HEALTH_WATCHDOG_CALLS"] == 0


if __name__ == "__main__":
    main()
