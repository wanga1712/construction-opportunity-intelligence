import importlib.util
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[1]
ENTRYPOINT = ROOT / "deploy" / "s13_dashboard3.py"
SPEC = importlib.util.spec_from_file_location("s13_dashboard3_single_screen", ENTRYPOINT)
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)
PAGE = dashboard.PAGE

FIXTURE = {
    "system_status": {"state": "WARNING"},
    "today_truth": {
        "received": 38, "denominator": 38,
        "commercial": {"denominator": 38, "accepted": 5, "rejected": 5, "processing": 2, "error": 26},
        "documents": {"needs_research": 5},
        "normalization": {"normalized": 0, "pending": 0},
        "ready_cards": {"count": 0},
        "ai_states": {"RUNNING": 2, "UNASSESSED": 26, "QUEUED": 0},
    },
    "runtime": {
        "assessment": {"state": "active", "pid": 1234, "procurement_id": 61049, "elapsed": 5},
        "feeder": {"state": "active"},
        "documents": {"workers_running": 0, "queue_working": 0, "queue_ready": 144, "stale": 16},
        "normalization": {"state": "OFF", "pending": 0},
        "autonomous": {"state": "failed"},
        "events": [
            {"time": "2026-11-17T17:03:00", "stage": "documents", "result": "DONE", "procurement": "?"},
            {"time": "2026-11-17T17:02:00", "stage": "assessment", "result": "DONE", "procurement": 61048},
            {"time": "2026-11-17T17:01:00", "stage": "feeder", "result": "DONE", "procurement": "?"},
        ],
    },
    "cpu_detail": {"busy_pct": 14, "per": [0, 0, 31, 0, 100, 0, 0, 0], "cap": {"cap_pct": 84, "min_pct": 42, "cur_mhz": 3110, "scaling_max_mhz": 3192, "hw_max_mhz": 3400, "no_turbo": True, "governor": "schedutil"}},
    "temperatures": {"package": 49, "core_max": 50, "display": 49},
    "gpu": {"util": 100, "temp": 64, "vram_used": 4799, "vram_total": 6144, "power": 79.8, "limit": 90, "default_limit": 125, "max_limit": 135, "headroom_w": 10.2, "clock_cur_mhz": 1950, "mem_clock_cur_mhz": 6801, "fan": 54, "power_state": "NOT_POWER_LIMITED", "throttle_reasons": []},
    "mem": {"pct": 40, "used": 12.7, "total": 31.3, "swap": 0.6},
    "cooling": {"fans": []},
    "disks": [{"mount": "/", "pct": 63, "health": "PASSED", "temp": None}],
    "command": {"commercial": {"live_total": 1742, "open": {"GOLD": 3, "SILVER": 19, "BRONZE": 156, "WOOD": 106}, "awarded": {"GOLD": 127, "SILVER": 847, "BRONZE": 183, "WOOD": 301}}},
}


def open_kiosk(page, width=1920, height=1080):
    def serve(route):
        if route.request.url.endswith("/api/metrics"):
            route.fulfill(status=200, content_type="application/json", body=__import__("json").dumps(FIXTURE))
        else:
            route.fulfill(status=200, content_type="text/html", body=PAGE)

    page.route("http://s13-kiosk.test/**", serve)
    page.set_viewport_size({"width": width, "height": height})
    page.goto("http://s13-kiosk.test/")
    page.wait_for_function("document.querySelectorAll('#todayPipeline .stage').length === 5")


def layout_state(page):
    return page.evaluate("""() => {
      const root = document.documentElement, main = document.querySelector('#screen-main');
      let outside = 0;
      for (const el of main.querySelectorAll('[data-fit]')) {
        const r = el.getBoundingClientRect();
        if (r.left < -2 || r.top < -2 || r.right > innerWidth + 2 || r.bottom > innerHeight + 2) outside++;
      }
      return {width: innerWidth, height: innerHeight, docWidth: root.scrollWidth,
        docHeight: root.scrollHeight, outside};
    }""")


def test_one_screen_only_and_required_contract():
    assert 'data-screen=' not in PAGE
    assert 'selectScreen' not in PAGE
    assert 'class="nav"' not in PAGE
    assert PAGE.count('id="screen-main"') == 1
    assert 'id="coreSummary"' in PAGE
    assert 'id="commercialMedals"' in PAGE
    assert 'setInterval(tick,3000)' in PAGE
    assert '<nav' not in PAGE and 'screen active' not in PAGE
    assert all(x not in PAGE for x in ['id="screen-resources"', 'id="screen-commercial"', 'manualUntil', 'createScreenController', 'setTimeout'])


def test_only_compact_hardware_fields_are_rendered():
    assert 'id="cpuLead"' in PAGE and 'id="coreSummary"' in PAGE
    assert "cap.cap_pct" in PAGE and "cap.scaling_max_mhz" in PAGE and "cap.no_turbo" in PAGE
    assert "g.util" in PAGE and "g.temp" in PAGE and "g.power" in PAGE and "g.limit" in PAGE
    assert "g.vram_used" in PAGE and "ram.pct" in PAGE
    assert all(x not in PAGE for x in ['id="diskList"', 'id="coolingInfo"', 'id="gpuThrottle"', 'g.default_limit', 'g.max_limit', 'g.headroom_w', 'g.clock_cur_mhz', 'g.mem_clock_cur_mhz', 'cap.min_pct', 'cap.hw_max_mhz'])


def test_today_pipeline_and_commercial_summary_are_single_and_truthful():
    assert PAGE.count('id="todayPipeline"') == 1
    assert "today_truth" in PAGE and "c.accepted" in PAGE and "needs_research" in PAGE
    assert "INITIAL SIGNAL" not in PAGE and "CLASSIFIED" not in PAGE
    assert 'id="commercialTotal"' in PAGE and 'id="openTotal"' in PAGE and 'id="awardedTotal"' in PAGE
    assert "['OPEN',o],['AWARDED',a]" in PAGE


def test_physical_layout_audit_contract():
    assert "function auditLayout()" in PAGE
    assert "root.scrollWidth" in PAGE and "root.scrollHeight" in PAGE
    assert "getBoundingClientRect()" in PAGE and "OUTSIDE " in PAGE


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768), (1280, 720)])
def test_browser_single_screen_contains_all_required_information(width, height):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        open_kiosk(page, width, height)
        state = layout_state(page)
        assert state["docWidth"] <= width, state
        assert state["docHeight"] <= height, state
        assert state["outside"] == 0, state
        assert page.locator("#screen-main").count() == 1
        assert page.locator("[data-screen]").count() == 0
        assert page.locator("nav").count() == 0
        assert page.locator("#nowTitle").inner_text().replace(chr(0xa0), " ").endswith("61 049")
        assert page.locator("#coreSummary .core-value").count() == 8
        assert page.locator("#cpuLead").inner_text()
        assert page.locator("#cpuCapSummary").inner_text()
        assert page.locator("#gpuLead").inner_text()
        assert page.locator("#gpuVram").inner_text()
        assert page.locator("#ramLead").inner_text()
        assert page.locator("#todayPipeline .stage").count() == 5
        assert page.locator("#attentionList .att-item").count() == 3
        assert page.locator("#eventList .event").count() == 3
        assert page.locator("#commercialTotal").inner_text().replace(chr(0xa0), " ") == "1 742"
        assert page.locator("#openTotal").inner_text().replace(chr(0xa0), " ") == "284"
        assert page.locator("#awardedTotal").inner_text().replace(chr(0xa0), " ") == "1 458"
        assert page.locator("#commercialMedals .medal-group").count() == 2
        assert "WARNING" in page.locator("#systemState").get_attribute("class")
        assert chr(0xfffd) not in page.locator("body").inner_text()
        browser.close()


def test_missing_temperature_and_gpu_values_render_na():
    assert "temp=function(v)" in PAGE and "pct=function(v)" in PAGE
    assert "v===null||v===undefined||!isFinite(Number(v))?L.na" in PAGE
