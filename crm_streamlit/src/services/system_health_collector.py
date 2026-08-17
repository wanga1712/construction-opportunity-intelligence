"""Background multi-host system health collector → atomic local snapshot."""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import resource  # Unix
except ImportError:
    resource = None  # type: ignore

from src.services.system_health_alerts import evaluate_host_alerts, overall_status, worst_status
from src.services.system_health_config import (
    COLLECTOR_VERSION,
    FAST_INTERVAL_SEC,
    HISTORY_AGG_INTERVAL_SEC,
    HOST_S13,
    HOST_S7,
    LAST_GOOD_SURVIVES_FAILURE,
    S7_FAILURE_BREAKS_S13_MONITORING,
    S7_INTERVAL_SEC,
    SMART_INTERVAL_SEC,
    state_dir,
)
from src.services.system_health_probes import (
    capability_audit,
    collect_block_devices,
    collect_cpu,
    collect_disk_io,
    collect_filesystems,
    collect_memory,
    collect_network,
    collect_top_processes,
    host_identity,
)
from src.services.system_health_s7 import collect_s7_host, s7_timeouts
from src.services.system_health_services import (
    audit_sdb_role,
    collect_crm_streamlit,
    collect_postgres,
    collect_services,
)
from src.services.system_health_smart import collect_all_disk_health, disk_summary_counts
from src.services.system_health_store import (
    append_history_metrics,
    ensure_history_db,
    read_history,
    read_latest,
    write_latest_safe,
)
from src.services.system_health_temps import collect_local_temperature_bundle, normalize_host_temperatures

assert LAST_GOOD_SURVIVES_FAILURE is True
assert S7_FAILURE_BREAKS_S13_MONITORING is False


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_s13_host(
    *,
    prev_host: Optional[Dict[str, Any]] = None,
    include_smart: bool = True,
) -> Dict[str, Any]:
    errors: list[str] = []

    def safe(label: str, fn):
        try:
            return fn()
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            return None

    last_cpu = ((prev_host or {}).get("cpu") or {}).get("usage_pct")
    caps = safe("capabilities", capability_audit) or {}
    host = safe("host", host_identity) or {}
    cpu = safe("cpu", lambda: collect_cpu(last_valid=last_cpu)) or {}
    mem = safe("memory", collect_memory) or {}
    filesystems = safe("filesystems", collect_filesystems) or []
    blocks = safe("block_devices", collect_block_devices) or []
    io = safe("disk_io", collect_disk_io) or {"devices": []}
    net = safe("network", collect_network) or []
    tops = safe("top_processes", lambda: collect_top_processes(8)) or {"by_cpu": [], "by_ram": []}
    services = safe("services", collect_services) or []
    postgres = safe("postgres", collect_postgres) or {}
    crm = safe("crm_streamlit", collect_crm_streamlit) or {}
    sdb_role = safe("sdb_role", audit_sdb_role) or {}

    if include_smart:
        disk_health = safe("smart", lambda: collect_all_disk_health(blocks)) or []
    else:
        disk_health = list((prev_host or {}).get("disk_health") or [])

    temps = safe("temperatures", collect_local_temperature_bundle) or {}
    disk_temps = [
        {"device": d.get("device"), "model": d.get("model"), "temp_c": d.get("temperature_c")}
        for d in disk_health
        if d.get("temperature_c") is not None
    ]
    if disk_temps:
        temps = normalize_host_temperatures(
            cpu_package=temps.get("cpu_package_temp_c"),
            cpu_core_max=temps.get("cpu_core_max_temp_c"),
            system_temp=temps.get("system_temp_c"),
            disk_temps=disk_temps,
            sensors_available=temps.get("S7_SENSORS_AVAILABLE"),
            thermal_sysfs_available=temps.get("S7_THERMAL_SYSFS_AVAILABLE"),
            cpu_temp_source=temps.get("cpu_temp_source"),
        )
    # keep legacy cpu.temp_c for charts/alerts
    if isinstance(cpu, dict) and temps.get("display_cpu_temp_c") is not None:
        cpu = dict(cpu)
        cpu["temp_c"] = temps.get("display_cpu_temp_c")

    from src.services.system_health_gpu import collect_s13_gpu_bundle

    gpu_bundle = safe("gpu_ollama", collect_s13_gpu_bundle) or {"gpu": {}, "ollama": {}}

    summary = disk_summary_counts(disk_health)
    physical_n = len(blocks)
    smart_ok_n = sum(1 for d in disk_health if d.get("available"))
    snap: Dict[str, Any] = {
        "host_id": HOST_S13,
        "reachable": True,
        "connectivity": "reachable",
        "role": "CRM / AI / Documents",
        "collected_at": _utcnow_iso(),
        "boot_time": host.get("boot_time"),
        "host": host,
        "capabilities": caps,
        "cpu": cpu,
        "memory": mem,
        "filesystems": filesystems,
        "block_devices": blocks,
        "disk_health": disk_health,
        "disk_summary": summary,
        "physical_disks_discovered": physical_n,
        "smart_accessible_devices": smart_ok_n,
        "temperatures": temps,
        "disk_io": io,
        "network": net,
        "services": services,
        "postgres": postgres,
        "crm_streamlit": crm,
        "top_processes": tops,
        "sdb_role": sdb_role,
        "gpu": gpu_bundle.get("gpu") or {},
        "ollama": gpu_bundle.get("ollama") or {},
        "collection_errors": errors,
        "smart_refreshed": include_smart,
    }
    prev_alerts = (prev_host or {}).get("alerts")
    snap["alerts"] = evaluate_host_alerts(HOST_S13, snap, prev_alerts)
    snap["overall_status"] = overall_status(snap["alerts"])
    return snap


def _history_cpu_values(host_id: str, root: Optional[Path] = None) -> list:
    rows = read_history(2.0, host_id=host_id, root=root)
    return [float(r["value"]) for r in rows if r.get("metric") == "cpu_pct" and r.get("value") is not None]


def _apply_alerts_with_history(host: Dict[str, Any], root: Optional[Path] = None) -> None:
    hid = host.get("host_id") or HOST_S13
    host["alerts"] = evaluate_host_alerts(
        hid,
        host,
        host.get("alerts"),
        history_cpu=_history_cpu_values(hid, root),
    )
    host["overall_status"] = overall_status(host["alerts"])


def build_multi_host_snapshot(
    *,
    collector_started_at: str,
    prev: Optional[Dict[str, Any]] = None,
    include_smart: bool = True,
    include_s7: bool = True,
) -> Dict[str, Any]:
    prev_hosts = (prev or {}).get("hosts") or {}
    # root for history lookups during alert rollup
    from src.services.system_health_config import state_dir as _state_dir

    hist_root = _state_dir()
    s13 = build_s13_host(prev_host=prev_hosts.get(HOST_S13), include_smart=include_smart)
    _apply_alerts_with_history(s13, hist_root)

    if include_s7:
        try:
            s7 = collect_s7_host()
        except Exception as exc:
            s7 = {
                "host_id": HOST_S7,
                "reachable": False,
                "connectivity": "unavailable",
                "collection_errors": [str(exc)],
                "alerts": [],
                "overall_status": "UNREACHABLE",
                "collected_at": _utcnow_iso(),
            }
        if not s7.get("reachable"):
            # keep last good S7 metrics if any
            old = prev_hosts.get(HOST_S7) or {}
            if old.get("reachable"):
                kept = dict(old)
                kept["reachable"] = False
                kept["connectivity"] = "stale"
                kept["stale_from"] = old.get("collected_at")
                kept["collection_errors"] = s7.get("collection_errors") or []
                kept["alerts"] = evaluate_host_alerts(HOST_S7, {"connectivity": "unavailable", "reachable": False}, old.get("alerts"))
                kept["overall_status"] = "STALE"
                s7 = kept
            else:
                s7["alerts"] = evaluate_host_alerts(HOST_S7, s7, None)
                s7["overall_status"] = "UNREACHABLE"
        else:
            s7["role"] = "Source / History / Collectors"
            # normalize temperatures from remote fields
            remote_temps = s7.get("temperatures") or {}
            if not remote_temps:
                s7["temperatures"] = normalize_host_temperatures(
                    cpu_package=(s7.get("cpu") or {}).get("temp_c"),
                    cpu_core_max=None,
                    disk_temps=[
                        {"device": d.get("device"), "model": d.get("model"), "temp_c": d.get("temperature_c")}
                        for d in (s7.get("disk_health") or [])
                        if d.get("temperature_c") is not None
                    ],
                    sensors_available=s7.get("S7_SENSORS_AVAILABLE"),
                    thermal_sysfs_available=s7.get("S7_THERMAL_SYSFS_AVAILABLE"),
                    cpu_temp_source=(s7.get("cpu") or {}).get("temp_source"),
                )
            s7["physical_disks_discovered"] = s7.get("physical_disks_discovered") or len(s7.get("block_devices") or [])
            s7["smart_accessible_devices"] = s7.get("smart_accessible_devices")
            if s7.get("smart_accessible_devices") is None:
                s7["smart_accessible_devices"] = sum(1 for d in (s7.get("disk_health") or []) if d.get("available"))
            s7["disk_summary"] = disk_summary_counts(s7.get("disk_health") or [])
            _apply_alerts_with_history(s7, hist_root)
    else:
        s7 = prev_hosts.get(HOST_S7) or {
            "host_id": HOST_S7,
            "reachable": False,
            "connectivity": "unavailable",
            "overall_status": "UNREACHABLE",
            "alerts": [],
        }

    all_alerts = list(s13.get("alerts") or []) + list(s7.get("alerts") or [])
    global_status = worst_status(s13.get("overall_status") or "OK", s7.get("overall_status") or "OK")

    snap: Dict[str, Any] = {
        "collector_version": COLLECTOR_VERSION,
        "collected_at": _utcnow_iso(),
        "collector_started_at": collector_started_at,
        "hosts": {HOST_S13: s13, HOST_S7: s7},
        "alerts": all_alerts,
        "S13_OVERALL_STATUS": s13.get("overall_status"),
        "S7_OVERALL_STATUS": s7.get("overall_status"),
        "GLOBAL_OVERALL_STATUS": global_status,
        "overall_status": global_status,
        "s13_to_s7_connectivity": s7.get("connectivity") or "unavailable",
        "s7_timeouts": s7_timeouts(),
        "S7_FAILURE_BREAKS_S13_MONITORING": False,
    }
    try:
        if resource is not None:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            snap["collector_self"] = {
                "rss_b": int(usage.ru_maxrss * 1024),
                "user_time_sec": usage.ru_utime,
                "sys_time_sec": usage.ru_stime,
            }
        else:
            snap["collector_self"] = {}
    except Exception:
        snap["collector_self"] = {}
    return snap


def _history_push(root: Path, snap: Dict[str, Any]) -> None:
    ts = time.time()
    for host_id, host in (snap.get("hosts") or {}).items():
        if not host:
            continue
        fs = {f.get("mount"): f for f in (host.get("filesystems") or [])}
        metrics = {
            "cpu_pct": (host.get("cpu") or {}).get("usage_pct"),
            "ram_used_pct": (host.get("memory") or {}).get("ram_used_pct"),
            "cpu_temp_c": (host.get("temperatures") or {}).get("display_cpu_temp_c")
            or (host.get("cpu") or {}).get("temp_c"),
            "root_used_pct": (fs.get("/") or {}).get("used_pct"),
            "data_used_pct": (fs.get("/data") or {}).get("used_pct"),
            "gpu_util_pct": (host.get("gpu") or {}).get("gpu_util_percent"),
            "gpu_temp_c": (host.get("gpu") or {}).get("gpu_temp_c"),
            "gpu_vram_pct": (host.get("gpu") or {}).get("gpu_vram_percent"),
            "gpu_power_w": (host.get("gpu") or {}).get("gpu_power_w"),
        }
        append_history_metrics(host_id, ts, metrics, root)


def run_collector_loop(
    *,
    root: Optional[Path] = None,
    fast_interval: float = FAST_INTERVAL_SEC,
    smart_interval: float = SMART_INTERVAL_SEC,
    s7_interval: float = S7_INTERVAL_SEC,
    max_iterations: Optional[int] = None,
) -> None:
    root = root or state_dir()
    root.mkdir(parents=True, exist_ok=True)
    ensure_history_db(root)
    started = _utcnow_iso()
    last_smart = 0.0
    last_s7 = 0.0
    last_hist = 0.0
    iterations = 0
    # warm local deltas (no S7)
    build_s13_host(include_smart=False)

    while True:
        iterations += 1
        prev = read_latest(root)
        now = time.time()
        do_smart = (now - last_smart) >= smart_interval or not prev
        do_s7 = (now - last_s7) >= s7_interval or not prev
        try:
            snap = build_multi_host_snapshot(
                collector_started_at=started,
                prev=prev,
                include_smart=do_smart,
                include_s7=do_s7,
            )
            # if S7 skipped this cycle, keep previous S7 block
            if not do_s7 and prev and (prev.get("hosts") or {}).get(HOST_S7):
                snap["hosts"][HOST_S7] = (prev.get("hosts") or {})[HOST_S7]
                snap["S7_OVERALL_STATUS"] = snap["hosts"][HOST_S7].get("overall_status")
                snap["s13_to_s7_connectivity"] = snap["hosts"][HOST_S7].get("connectivity")
                snap["alerts"] = list(snap["hosts"][HOST_S13].get("alerts") or []) + list(
                    snap["hosts"][HOST_S7].get("alerts") or []
                )
                snap["GLOBAL_OVERALL_STATUS"] = worst_status(
                    snap["S13_OVERALL_STATUS"], snap["S7_OVERALL_STATUS"]
                )
                snap["overall_status"] = snap["GLOBAL_OVERALL_STATUS"]
            write_latest_safe(snap, root)
            if do_smart:
                last_smart = now
            if do_s7:
                last_s7 = now
            if (now - last_hist) >= HISTORY_AGG_INTERVAL_SEC:
                _history_push(root, snap)
                last_hist = now
        except Exception:
            err_path = root / "collector_last_error.txt"
            err_path.write_text(traceback.format_exc(), encoding="utf-8")
        if max_iterations is not None and iterations >= max_iterations:
            return
        time.sleep(fast_interval)
