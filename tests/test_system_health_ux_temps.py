"""UX + temperature contracts for multi-host system health."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.services import system_health_alerts as alerts
from src.services import system_health_config as cfg
from src.services import system_health_read as read
from src.services import system_health_temps as temps
from src.services.system_health_store import write_latest_safe
from src.ui import system_health_format as fmt

ROOT = Path(__file__).resolve().parents[1]


def test_temp_unknown_not_zero():
    assert temps.temp_status(None) == "UNKNOWN"
    assert temps.S7_TEMP_FAKE_VALUE is False
    assert cfg.S7_TEMP_FAKE_VALUE is False
    assert fmt.fmt_temp(None) == "Недоступно"
    assert fmt.fmt_temp(0) == "0°C"  # real zero allowed only if measured


def test_temp_policy_thresholds():
    assert cfg.CPU_TEMP_WARN_C == 70.0
    assert cfg.CPU_TEMP_CRIT_C == 85.0
    assert cfg.DISK_TEMP_WARN_C == 50.0
    assert cfg.DISK_TEMP_CRIT_C == 60.0
    assert temps.temp_status(38, kind="cpu") == "OK"
    assert temps.temp_status(75, kind="cpu") == "WARNING"
    assert temps.temp_status(90, kind="cpu") == "CRITICAL"
    assert temps.temp_status(45, kind="disk") == "OK"
    assert temps.temp_status(55, kind="disk") == "WARNING"


def test_normalize_temps_and_disk_list():
    n = temps.normalize_host_temperatures(
        cpu_package=38.0,
        cpu_core_max=39.0,
        disk_temps=[{"device": "/dev/sda", "model": "X", "temp_c": 30}],
    )
    assert n["display_cpu_temp_c"] == 38.0
    assert n["disk_temperatures"][0]["temp_c"] == 30
    assert n["display_cpu_temp_status"] == "OK"


def test_zero_smart_not_zero_disks():
    assert cfg.ZERO_SMART_ACCESS_NOT_EQUAL_ZERO_DISKS is True
    line, st = fmt.disk_summary_ru(
        {"physical_disks_discovered": 2, "smart_accessible_devices": 0, "disk_summary": {}}
    )
    assert "Физических дисков: 2" in line
    assert "SMART" in line
    assert "0/0" not in line


def test_human_readable_timestamp_and_load():
    iso = "2026-08-12T16:53:47.204746+00:00"
    out = fmt.fmt_ts_local(iso)
    assert "T" not in out
    assert "." in out or ":" in out
    assert len(out) <= 22
    load = fmt.fmt_load({"load_1": 0.10888671875, "load_5": 0.14, "load_15": 0.10, "cores": 8})
    assert "0.10888671875" not in load
    assert "8 потоков" in load


def test_history_not_on_overview_contract():
    assert cfg.HISTORY_LOADED_ON_OVERVIEW is False


def test_history_loaded_flag(tmp_path):
    write_latest_safe(
        {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "GLOBAL_OVERALL_STATUS": "OK",
            "hosts": {"S13": {"host_id": "S13", "collected_at": datetime.now(timezone.utc).isoformat()}, "S7": {"host_id": "S7"}},
            "alerts": [],
        },
        tmp_path,
    )
    overview = read.load_dashboard(tmp_path, include_history=False)
    assert overview["history_loaded"] is False
    assert overview["history"] == []
    detail = read.load_dashboard(tmp_path, include_history=True, history_host="S13", history_hours=1)
    assert detail["history_loaded"] is True


def test_sustained_cpu_alert():
    assert cfg.SUSTAINED_CPU_ALERT is True
    host = {
        "host_id": "S7",
        "cpu": {"usage_pct": 95},
        "filesystems": [],
        "disk_health": [],
        "services": [],
        "source_collectors": [],
        "postgres": {},
        "crm_streamlit": {},
        "temperatures": {},
    }
    a = alerts.evaluate_host_alerts("S7", host, history_cpu=[91, 92, 93, 94, 95])
    assert any("sustained CPU" in (x.get("message") or "") for x in a)
    b = alerts.evaluate_host_alerts("S7", host, history_cpu=[91, 50, 95, 96, 97])
    assert not any("sustained CPU" in (x.get("message") or "") for x in b)


def test_ui_page_contracts():
    src = (ROOT / "src/ui/system_health_page.py").read_text(encoding="utf-8")
    assert "Техническая информация" in src
    assert "Источник данных" in src
    assert "LEGACY" in src or "не используется" in src
    assert "subprocess" not in src
    assert "include_history=need_hist" in src or "include_history=need_hist" in src.replace(" ", "")
    assert "Состояние дисков" in src
    assert PAGE_LABEL_OK()


def PAGE_LABEL_OK():
    assert cfg.PAGE_LABEL == "Состояние серверов"
    nav = (ROOT / "src/ui/nav.py").read_text(encoding="utf-8")
    return "Состояние серверов" in nav


def test_paused_services_copy():
    src = (ROOT / "src/ui/system_health_page.py").read_text(encoding="utf-8")
    assert "Остановлено по текущему плану" in src


def test_two_host_overview_markers():
    src = (ROOT / "src/ui/system_health_page.py").read_text(encoding="utf-8")
    assert "SERVER 13" in src and "SERVER 7" in src
    assert "_host_overview_card" in src
