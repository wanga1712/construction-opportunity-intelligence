"""Contracts for multi-host CRM system health dashboard."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.services import system_health_alerts as alerts
from src.services import system_health_config as cfg
from src.services import system_health_read as read
from src.services import system_health_smart as smart
from src.services import system_health_store as store
from src.services.system_health_collector import build_multi_host_snapshot, build_s13_host
from src.services.system_health_services import _classify_oneshot_timer, audit_sdb_role

ROOT = Path(__file__).resolve().parents[1]
HAS_PROC = Path("/proc/stat").is_file()


def test_page_label_multi_host():
    assert cfg.PAGE_LABEL == "Состояние серверов"
    assert cfg.MONITORED_HOSTS == ("S13", "S7")
    nav = (ROOT / "src/ui/nav.py").read_text(encoding="utf-8")
    assert "Состояние серверов" in nav


def test_s7_ssh_never_on_ui():
    assert cfg.S7_SSH_CALLS_ON_UI_RERUN == 0
    ui = (ROOT / "src/ui/system_health_page.py").read_text(encoding="utf-8")
    assert "ssh" not in ui.lower() or "S7_SSH_CALLS_ON_UI_RERUN" in ui
    assert "subprocess" not in ui
    read_src = (ROOT / "src/services/system_health_read.py").read_text(encoding="utf-8")
    assert "ssh" not in read_src.lower() or "S7_SSH" in read_src


def test_smart_overall_pass_does_not_hide_sector_errors():
    assert cfg.SMART_OVERALL_PASS_HIDES_SECTOR_ERRORS is False
    d = {
        "available": True,
        "overall": "PASSED",
        "kind": "ata",
        "reallocated_sectors": 36,
        "pending_sectors": 3,
        "offline_uncorrectable": 0,
        "temperature_c": 29,
    }
    assert smart.derive_physical_status(d) == "WARNING"
    counts = smart.disk_summary_counts([{**d, "device": "/dev/sdb"}, {"available": True, "overall": "PASSED", "kind": "ata", "status": "OK", "device": "/dev/sda", "reallocated_sectors": 0, "pending_sectors": 0}])
    # after derive, sdb warning
    assert counts["WARNING"] >= 1
    assert counts["OK"] >= 1
    assert counts["OK"] != 2 or counts["WARNING"] > 0


def test_disk_summary_matches_device_alerts():
    host = {
        "host_id": "S13",
        "filesystems": [],
        "cpu": {},
        "disk_health": [
            {"device": "/dev/sda", "available": True, "overall": "PASSED", "kind": "ata", "reallocated_sectors": 0, "pending_sectors": 0},
            {"device": "/dev/sdb", "available": True, "overall": "PASSED", "kind": "ata", "reallocated_sectors": 36, "pending_sectors": 3},
            {"device": "/dev/sdc", "available": True, "overall": "PASSED", "kind": "ata", "reallocated_sectors": 0, "pending_sectors": 0},
        ],
        "services": [],
        "postgres": {},
        "crm_streamlit": {},
    }
    for d in host["disk_health"]:
        d["status"] = smart.derive_physical_status(d)
    a = alerts.evaluate_host_alerts("S13", host)
    assert any(x["device_or_service"] == "/dev/sdb" and x["host_id"] == "S13" for x in a)
    assert all(x.get("host_id") for x in a)
    summary = smart.disk_summary_counts(host["disk_health"])
    assert summary["OK"] == 2
    assert summary["WARNING"] == 1


def test_transient_oneshot_not_critical(monkeypatch):
    assert cfg.TRANSIENT_ONESHOT_RUNNING_IS_CRITICAL is False

    def fake_state(unit: str):
        if unit.endswith(".timer"):
            return {
                "unit": unit,
                "active": "active",
                "enabled": "enabled",
                "type": "oneshot",
                "sub_state": "waiting",
                "result": "success",
                "exec_main_status": "0",
                "active_enter": "",
                "inactive_exit": "",
                "exec_main_start": "",
            }
        return {
            "unit": unit,
            "active": "activating",
            "enabled": "static",
            "type": "oneshot",
            "sub_state": "start",
            "result": "success",
            "exec_main_status": "0",
            "active_enter": "",
            "inactive_exit": "Wed",
            "exec_main_start": "",
        }

    monkeypatch.setattr("src.services.system_health_services._unit_state", fake_state)
    monkeypatch.setattr(
        "src.services.system_health_services._unit_props",
        lambda unit, props: {p: ("Wed" if "Last" in p else "success") for p in props},
    )
    row = _classify_oneshot_timer("crm-procurement-sync.service", "crm-procurement-sync.timer")
    assert row["ui_status"] != "CRITICAL"
    assert row["health_model"] == "ONESHOT_RUNNING"


def test_invalid_cpu_not_zero():
    assert cfg.INVALID_CPU_SAMPLE_DISPLAYED_AS_ZERO is False
    from src.services import system_health_probes as probes

    with patch.object(probes, "_cpu_percent_sample", return_value={"total": None, "per_core": []}):
        probes._last_valid_cpu_pct = None
        cpu = probes.collect_cpu(last_valid=None)
        assert cpu["usage_pct"] is None
        assert cpu["usage_pct_status"] == "NOT_AVAILABLE"
        assert cpu["usage_pct"] != 0.0


def test_s7_failure_does_not_break_s13(monkeypatch):
    assert cfg.S7_FAILURE_BREAKS_S13_MONITORING is False

    def boom():
        raise RuntimeError("ssh fail")

    monkeypatch.setattr("src.services.system_health_collector.collect_s7_host", boom)
    if not HAS_PROC:
        # still build multi with mocked s13
        monkeypatch.setattr(
            "src.services.system_health_collector.build_s13_host",
            lambda **k: {
                "host_id": "S13",
                "overall_status": "OK",
                "alerts": [],
                "reachable": True,
                "cpu": {"usage_pct": 1.0},
                "memory": {},
                "filesystems": [],
                "disk_health": [],
            },
        )
    snap = build_multi_host_snapshot(collector_started_at="t0", include_smart=False, include_s7=True)
    assert snap["hosts"]["S13"]["overall_status"] in ("OK", "WARNING", "CRITICAL")
    assert snap["hosts"]["S7"]["overall_status"] in ("UNREACHABLE", "STALE", "WARNING")
    assert snap["S7_FAILURE_BREAKS_S13_MONITORING"] is False


def test_per_host_and_global_status():
    snap = {
        "hosts": {
            "S13": {"overall_status": "WARNING"},
            "S7": {"overall_status": "OK"},
        }
    }
    assert alerts.worst_status("WARNING", "OK") == "WARNING"
    assert alerts.worst_status("OK", "CRITICAL") == "CRITICAL"


def test_history_multi_host(tmp_path):
    assert cfg.HEALTH_HISTORY_MULTI_HOST is True
    store.append_history_metrics("S13", time.time(), {"cpu_pct": 1.5}, tmp_path)
    store.append_history_metrics("S7", time.time(), {"cpu_pct": 2.5}, tmp_path)
    rows = store.read_history(24, root=tmp_path)
    hosts = {r["host_id"] for r in rows}
    assert "S13" in hosts and "S7" in hosts
    assert all("metric" in r and "value" in r for r in rows)


def test_ui_read_no_ssh(tmp_path, monkeypatch):
    store.write_latest_safe(
        {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "GLOBAL_OVERALL_STATUS": "OK",
            "hosts": {
                "S13": {"host_id": "S13", "overall_status": "OK", "collected_at": datetime.now(timezone.utc).isoformat()},
                "S7": {"host_id": "S7", "overall_status": "OK", "collected_at": datetime.now(timezone.utc).isoformat()},
            },
            "alerts": [],
        },
        tmp_path,
    )
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("ssh from UI")

    monkeypatch.setattr("src.services.system_health_s7.collect_s7_host", boom)
    view = read.load_dashboard(tmp_path)
    assert view["s7_ssh_calls"] == 0
    assert view["hardware_probes"] == 0
    assert called["n"] == 0
    assert "S13" in view["monitored_hosts"] and "S7" in view["monitored_hosts"]


def test_alert_host_id_required():
    a = alerts.evaluate_host_alerts(
        "S13",
        {
            "filesystems": [{"mount": "/data", "used_pct": 96}],
            "cpu": {},
            "disk_health": [],
            "services": [],
            "postgres": {},
            "crm_streamlit": {},
        },
    )
    assert a and all(x["host_id"] == "S13" for x in a)


@pytest.mark.skipif(not HAS_PROC, reason="Linux only")
def test_sdb_role_identified():
    role = audit_sdb_role()
    assert "SDB_DATA_ROLE" in role
    assert "SDB_PARTITIONS" in role
    assert role.get("IS_SDB_CURRENTLY_UNUSED") in (True, False)


def test_s7_timeouts_configured():
    assert cfg.S7_CONNECT_TIMEOUT > 0
    assert cfg.S7_COMMAND_TIMEOUT > 0
    assert cfg.S7_COLLECTION_TIMEOUT >= cfg.S7_COMMAND_TIMEOUT
