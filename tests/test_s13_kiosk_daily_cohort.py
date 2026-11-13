import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy" / "s13_dashboard3.py"


def _load_dashboard():
    spec = importlib.util.spec_from_file_location("s13_dashboard3_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_daily_contract_uses_one_researchable_today_cohort(monkeypatch):
    dashboard = _load_dashboard()
    monkeypatch.setattr(dashboard, "routing_backlog_count", lambda: 0)

    daily, contour = dashboard.daily_work_contract(
        {
            "today": {
                "received": 38,
                "researchable_from_received": 38,
                "with_initial_signal": 17,
                "without_initial_signal": 21,
                "processed_from_received": 10,
                "in_progress_from_received": 5,
                "processed": 18,
            },
            "documents": {"waiting": 200},
        },
        {"latest": {"eligible_total": 100, "processed_total": 70,
                    "remaining_total": 30}},
    )

    assert daily["received_today"] == 38
    assert daily["researchable_today"] == 38
    assert daily["with_initial_signal"] == 17
    assert daily["without_initial_signal"] == 21
    assert daily["processed_from_day_work_set"] == 10
    assert daily["in_progress_from_day_work_set"] == 5
    assert daily["remaining_from_day_work_set"] == 28
    assert daily["daily_progress_pct"] == 26.3
    assert daily["routing_backlog"] == 0
    assert daily["document_queue_pending"] == 200
    assert contour["remaining_total"] == 30


def test_no_initial_signal_remains_in_research_remaining(monkeypatch):
    dashboard = _load_dashboard()
    monkeypatch.setattr(dashboard, "routing_backlog_count", lambda: 0)

    daily, _ = dashboard.daily_work_contract(
        {
            "today": {
                "received": 38,
                "researchable_from_received": 38,
                "with_initial_signal": 5,
                "without_initial_signal": 33,
                "processed_from_received": 3,
                "in_progress_from_received": 4,
            },
            "documents": {"waiting": 200},
        },
        {"latest": {}},
    )

    assert daily["without_initial_signal"] == 33
    assert daily["remaining_from_day_work_set"] == 35
    assert daily["daily_progress_pct"] == 7.9
