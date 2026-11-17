import importlib.util
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[1]
ENTRYPOINT = ROOT / "deploy" / "s13_dashboard3.py"
SPEC = importlib.util.spec_from_file_location("s13_dashboard3_physical", ENTRYPOINT)
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)
PAGE = dashboard.PAGE

FIXTURE = {
    "system_status": {"state": "WARNING"},
    "today_truth": {
        "received": 38,
        "denominator": 38,
        "commercial": {"denominator": 38, "accepted": 5, "rejected": 5, "processing": 2, "error": 26},
        "documents": {"needs_research": 5},
        "normalization": {"normalized": 0, "pending": 0},
        "ready_cards": {"count": 0},
        "ai_states": {"RUNNING": 2, "UNASSESSED": 26, "QUEUED": 0},
    },
    "runtime": {
        "assessment": {"state": "active", "pid": 1234, "procurement_id": 322905, "elapsed": 17},
        "feeder": {"state": "active"},
        "documents": {"workers_running": 0, "queue_working": 0, "queue_ready": 205, "stale": 16},
        "normalization": {"state": "OFF", "pending": 0},
        "autonomous": {"state": "failed"},
        "gpu_model": "Qwen 2.5 7B",
        "events": [
            {"time": "2026-11-17T13:14:00", "stage": "assessment", "result": "DONE", "procurement": 322904},
            {"time": "2026-11-17T13:13:00", "stage": "assessment", "result": "START", "procurement": 322905},
            {"time": "2026-11-17T13:12:00", "stage": "feeder", "result": "DONE", "procurement": "?"},
        ],
    },
    "cpu_detail": {"busy_pct": 52, "per": [0, 0, 34, 0, 0, 100, 3, 0], "cap": {"cap_pct": 84, "min_pct": 42, "cur_mhz": 3108, "scaling_max_mhz": 3192, "hw_max_mhz": 3400, "no_turbo": True, "governor": "schedutil"}},
    "temperatures": {"package": 52, "core_max": 54, "display": 52},
    "gpu": {"util": 100, "temp": 65, "vram_used": 4799, "vram_total": 6144, "power": 79.4, "limit": 90, "default_limit": 125, "max_limit": 135, "headroom_w": 10.6, "clock_cur_mhz": 1935, "mem_clock_cur_mhz": 6801, "fan": 58, "power_state": "NOT_POWER_LIMITED", "throttle_reasons": []},
    "mem": {"pct": 40, "used": 12.6, "total": 31.3, "swap": 0.6},
    "cooling": {"fans": []},
    "disks": [{"mount": "/", "pct": 63, "health": "PASSED", "temp": None}, {"mount": "/data", "pct": 29, "health": "PASSED", "temp": 40}],
    "command": {"commercial": {"live_total": 1742, "open": {"GOLD": 3, "SILVER": 19, "BRONZE": 156, "WOOD": 106}, "awarded": {"GOLD": 127, "SILVER": 847, "BRONZE": 183, "WOOD": 301}}},
}


def open_kiosk(page, width, height):
    def serve(route):
        if route.request.url.endswith("/api/metrics"):
            route.fulfill(status=200, content_type="application/json", body=__import__("json").dumps(FIXTURE))
        else:
            route.fulfill(status=200, content_type="text/html", body=PAGE)

    page.route("http://s13-kiosk.test/**", serve)
    page.set_viewport_size({"width": width, "height": height})
    page.goto("http://s13-kiosk.test/")
    page.wait_for_function("document.querySelector('#todayPipeline .stage')")


def layout_state(page):
    return page.evaluate("""() => {
      const root = document.documentElement;
      const active = document.querySelector('.screen.active');
      let outside = 0;
      for (const el of active.querySelectorAll('[data-fit]')) {
        const r = el.getBoundingClientRect();
        if (r.left < -2 || r.top < -2 || r.right > innerWidth + 2 || r.bottom > innerHeight + 2) outside++;
      }
      return {width: innerWidth, height: innerHeight, docWidth: root.scrollWidth,
        docHeight: root.scrollHeight, outside, active: active.dataset.screen};
    }""")


def test_two_manual_primary_screens_and_no_rotation():
    assert PAGE.count('class="screen active"') == 1
    assert PAGE.count('class="screen') == 2
    assert 'data-screen="OPERATIONS"' in PAGE and 'data-screen="RESOURCES"' in PAGE
    assert "createScreenController" not in PAGE and "setTimeout" not in PAGE
    assert "manualUntil" not in PAGE and "setCritical" not in PAGE
    assert "setInterval(tick,3000)" in PAGE  # data polling remains independent from screen selection
    assert "setAttribute('dir'" not in PAGE and "direction:ltr!important" not in PAGE


def test_operations_has_single_pipeline_and_compact_commercial_summary():
    assert PAGE.count('id="todayPipeline"') == 1
    assert PAGE.count('data-fit') >= 8
    assert "today_truth" in PAGE and "c.accepted" in PAGE and "needs_research" in PAGE
    assert "COMMERCIAL" not in PAGE[PAGE.index('id="screen-operations"'):PAGE.index('id="screen-resources"')]
    assert "INITIAL SIGNAL" not in PAGE and "CLASSIFIED" not in PAGE
    assert 'id="commercialMedals"' in PAGE and 'id="openTotal"' in PAGE


def test_resources_render_every_core_and_hardware_values():
    assert "p.map(function(v,i)" in PAGE
    assert "t.package" in PAGE and "t.core_max" in PAGE
    assert "cap.scaling_max_mhz" in PAGE and "cap.hw_max_mhz" in PAGE
    assert "g.default_limit" in PAGE and "g.max_limit" in PAGE and "g.vram_used" in PAGE


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768), (1280, 720)])
def test_real_browser_layout_and_manual_selection(width, height):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        open_kiosk(page, width, height)
        assert page.locator("#todayPipeline .stage").count() == 5
        labels = page.locator("#todayPipeline .stage-label").all_text_contents()
        expected = [bytes.fromhex(x).decode("utf-8") for x in [
            "d09fd09ed0a1d0a2d0a3d09fd098d09bd09e", "d09ad09ed09cd09cd095d0a0d0a7d095d0a1d09ad098d09920d09ed0a2d091d09ed0a0", "d094d09ed09ad0a3d09cd095d09dd0a2d0ab", "d09dd09ed0a0d09cd090d09bd098d097d090d0a6d098d0af", "d093d09ed0a2d09ed092d09e"
        ]]
        assert labels == expected
        assert page.locator("#attentionList .att-item").count() <= 3
        for screen, key in [("OPERATIONS", "1"), ("RESOURCES", "2")]:
            page.keyboard.press(key)
            page.wait_for_function("(screen) => document.querySelector('.screen.active').dataset.screen === screen", arg=screen)
            state = layout_state(page)
            assert state["active"] == screen
            assert state["docWidth"] <= width, state
            assert state["docHeight"] <= height, state
            assert state["outside"] == 0, state
            assert page.evaluate("""() => [document.body,document.querySelector('header'),document.querySelector('nav'),document.querySelector('main'),document.querySelector('.flow')].every(el => getComputedStyle(el).direction === 'ltr')""")
            if screen == "RESOURCES":
                assert page.locator("#cpuCores .core").count() == 8
                assert page.locator("#gpuMetrics .metric").count() == 9
        assert "WARNING" in page.locator("#systemState").get_attribute("class")
        assert "\ufffd" not in page.locator("body").inner_text()
        browser.close()


def test_missing_temperatures_and_gpu_metrics_render_na():
    assert "temp=function(v)" in PAGE and "pct=function(v)" in PAGE
    assert "v===null||v===undefined||!isFinite(Number(v))?L.na" in PAGE


def test_physical_layout_audit_and_loader_are_real():
    assert "function auditLayout()" in PAGE
    assert "root.scrollWidth" in PAGE and "root.scrollHeight" in PAGE
    assert "getBoundingClientRect()" in PAGE and "OUTSIDE " in PAGE
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'PAGE=load_kiosk_page("s13_kiosk_main.html")' in source
