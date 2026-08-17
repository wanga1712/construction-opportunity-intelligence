"""Service / Postgres / CRM Streamlit health (oneshot/timer aware)."""
from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services.system_health_config import (
    EXPECTED_INACTIVE_IS_FAILURE,
    SERVICE_EXPECTED_ACTIVE,
    SERVICE_EXPECTED_FROZEN,
    SERVICE_ONESHOT_TIMER,
    SERVICE_WATCH_OPTIONAL,
    TRANSIENT_ONESHOT_RUNNING_IS_CRITICAL,
)

assert EXPECTED_INACTIVE_IS_FAILURE is False
assert TRANSIENT_ONESHOT_RUNNING_IS_CRITICAL is False


def _systemctl(*args: str, timeout: float = 5) -> str:
    try:
        r = subprocess.run(
            ["systemctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _unit_props(unit: str, props: List[str]) -> Dict[str, str]:
    args: List[str] = [unit]
    for p in props:
        args.extend(["-p", p])
    raw = _systemctl("show", *args)
    parsed: Dict[str, str] = {}
    for line in (raw or "").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        parsed[k] = v
    return {p: parsed.get(p, "") for p in props}


def _unit_state(unit: str) -> Dict[str, Any]:
    active = _systemctl("is-active", unit) or "unknown"
    enabled = _systemctl("is-enabled", unit) or "unknown"
    props = _unit_props(
        unit,
        [
            "Type",
            "SubState",
            "Result",
            "ExecMainStatus",
            "ActiveEnterTimestamp",
            "InactiveExitTimestamp",
            "ExecMainStartTimestamp",
        ],
    )
    return {
        "unit": unit,
        "active": active,
        "enabled": enabled,
        "type": props.get("Type") or "",
        "sub_state": props.get("SubState") or "",
        "result": props.get("Result") or "",
        "exec_main_status": props.get("ExecMainStatus") or "",
        "active_enter": props.get("ActiveEnterTimestamp") or "",
        "inactive_exit": props.get("InactiveExitTimestamp") or "",
        "exec_main_start": props.get("ExecMainStartTimestamp") or "",
    }


def _classify_oneshot_timer(service: str, timer: str) -> Dict[str, Any]:
    st = _unit_state(service)
    tm = _unit_state(timer)
    timer_props = _unit_props(timer, ["LastTriggerUSec", "NextElapseUSecRealtime", "Result"])
    st["timer"] = timer
    st["timer_active"] = tm.get("active")
    st["timer_last_trigger"] = timer_props.get("LastTriggerUSec") or ""
    st["timer_next"] = timer_props.get("NextElapseUSecRealtime") or ""
    st["timer_result"] = timer_props.get("Result") or tm.get("result") or ""
    st["expectation"] = "ONESHOT_TIMER"

    active = st.get("active") or ""
    sub = st.get("sub_state") or ""
    result = (st.get("result") or "").lower()

    if active == "activating" or sub in ("start", "running"):
        st["health_model"] = "ONESHOT_RUNNING"
        st["ui_status"] = "OK"
        st["message"] = "oneshot currently running (not CRITICAL)"
        return st
    if result in ("failed", "timeout", "exit-code") and active == "failed":
        st["health_model"] = "ONESHOT_FAILED"
        st["ui_status"] = "CRITICAL"
        st["message"] = "oneshot last result failed"
        return st
    if tm.get("active") == "active":
        st["health_model"] = "TIMER_HEALTHY" if result in ("success", "", "n/a") or active in (
            "inactive",
            "dead",
        ) else "ONESHOT_IDLE"
        if result == "failed":
            st["ui_status"] = "WARNING"
            st["message"] = "timer active but last oneshot result failed"
        else:
            st["health_model"] = "ONESHOT_IDLE" if active in ("inactive", "dead") else "TIMER_HEALTHY"
            st["ui_status"] = "OK"
            st["message"] = "timer healthy / oneshot idle"
        return st
    if tm.get("active") in ("inactive", "dead") and tm.get("enabled") in ("disabled", "masked"):
        st["health_model"] = "DISABLED_EXPECTED"
        st["ui_status"] = "INFO"
        st["message"] = "timer disabled"
        return st
    st["health_model"] = "ONESHOT_IDLE"
    st["ui_status"] = "WARNING"
    st["message"] = "oneshot/timer unexpected state"
    return st


def collect_services() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for unit in SERVICE_EXPECTED_ACTIVE:
        st = _unit_state(unit)
        st["expectation"] = "LONG_RUNNING"
        st["health_model"] = "LONG_RUNNING"
        if st["active"] == "active":
            st["ui_status"] = "OK"
        else:
            st["ui_status"] = "CRITICAL"
            st["message"] = "expected active but not active"
        rows.append(st)

    for service, timer in SERVICE_ONESHOT_TIMER.items():
        rows.append(_classify_oneshot_timer(service, timer))

    for unit in SERVICE_EXPECTED_FROZEN:
        st = _unit_state(unit)
        st["expectation"] = "FROZEN"
        st["health_model"] = "FROZEN"
        if st["active"] == "active":
            st["ui_status"] = "WARNING"
            st["message"] = "frozen unit is unexpectedly active"
        else:
            st["ui_status"] = "PAUSED"
            st["message"] = "intentionally frozen"
        rows.append(st)

    for unit in SERVICE_WATCH_OPTIONAL:
        st = _unit_state(unit)
        st["expectation"] = "OPTIONAL"
        st["health_model"] = "OPTIONAL"
        st["ui_status"] = "OK" if st["active"] == "active" else "INFO"
        rows.append(st)
    return rows


def collect_postgres() -> Dict[str, Any]:
    unit = _unit_state("postgresql.service")
    unit17 = _unit_state("postgresql@17-main.service")
    reachable = False
    version = None
    try:
        s = socket.create_connection(("127.0.0.1", 5432), timeout=1.5)
        s.close()
        reachable = True
    except Exception:
        reachable = False
    try:
        r = subprocess.run(
            ["psql", "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        version = (r.stdout or "").strip() or None
    except Exception:
        pass
    db_sizes: Dict[str, Any] = {}
    for db in ("document_intelligence", "postgres"):
        try:
            r = subprocess.run(
                [
                    "psql",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "postgres",
                    "-d",
                    "postgres",
                    "-tAc",
                    f"SELECT pg_database_size('{db}')",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if r.returncode == 0 and (r.stdout or "").strip().isdigit():
                db_sizes[db] = int((r.stdout or "").strip())
            else:
                db_sizes[db] = "UNAVAILABLE"
        except Exception:
            db_sizes[db] = "UNAVAILABLE"
    active = unit["active"] == "active" or unit17["active"] == "active"
    return {
        "service_active": active,
        "unit": unit,
        "unit_versioned": unit17,
        "reachable_127_5432": reachable,
        "version": version,
        "db_sizes": db_sizes,
        "ui_status": "OK" if active and reachable else ("WARNING" if active else "CRITICAL"),
    }


def collect_crm_streamlit() -> Dict[str, Any]:
    unit = _unit_state("crm-streamlit.service")
    pid = None
    try:
        pid_s = _systemctl("show", "-p", "MainPID", "--value", "crm-streamlit.service")
        pid = int(pid_s) if pid_s and pid_s.isdigit() and int(pid_s) > 0 else None
    except Exception:
        pid = None
    http_ok = False
    http_ms = None
    try:
        import urllib.request

        t0 = time.time()
        with urllib.request.urlopen("http://127.0.0.1:8504/", timeout=2) as resp:
            http_ok = 200 <= getattr(resp, "status", 200) < 400
        http_ms = round((time.time() - t0) * 1000, 1)
    except Exception:
        http_ok = False
    rss_b = uptime_sec = None
    if pid:
        try:
            status = Path(f"/proc/{pid}/status").read_text()
            for ln in status.splitlines():
                if ln.startswith("VmRSS:"):
                    rss_b = int(ln.split()[1]) * 1024
            stat = Path(f"/proc/{pid}/stat").read_text()
            rparen = stat.rfind(")")
            fields = stat[rparen + 2 :].split()
            start_ticks = int(fields[19])
            hz = 100
            try:
                import os

                hz = os.sysconf("SC_CLK_TCK")
            except Exception:
                pass
            boot = float(Path("/proc/uptime").read_text().split()[0])
            uptime_sec = max(0.0, boot - start_ticks / hz)
        except Exception:
            pass
    return {
        "unit": unit,
        "pid": pid,
        "http_ok": http_ok,
        "http_ms": http_ms,
        "rss_b": rss_b,
        "uptime_sec": uptime_sec,
        "ui_status": "OK"
        if unit["active"] == "active" and http_ok
        else ("WARNING" if unit["active"] == "active" else "CRITICAL"),
    }


def audit_sdb_role() -> Dict[str, Any]:
    """READ-ONLY: determine whether /dev/sdb is used by live stacks."""
    import json

    partitions: List[str] = []
    mount_points: List[str] = []
    filesystems: List[str] = []
    try:
        r = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,FSTYPE,MOUNTPOINTS,TYPE", "/dev/sdb"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        data = json.loads(r.stdout or "{}")
        for node in data.get("blockdevices") or []:

            def walk(n):
                name = n.get("name")
                if n.get("type") == "part" and name:
                    partitions.append(f"/dev/{name}")
                ft = n.get("fstype")
                if ft:
                    filesystems.append(ft)
                mp = n.get("mountpoints") or []
                if isinstance(mp, list):
                    mount_points.extend([m for m in mp if m])
                for ch in n.get("children") or []:
                    walk(ch)

            walk(node)
    except Exception as exc:
        return {"error": str(exc), "SDB_DATA_ROLE": "UNKNOWN"}

    # Important live mounts
    live = {}
    for path in ("/", "/data", "/var/lib/postgresql", "/opt/CRM_Streamlit", "/var/lib/crm-system-health"):
        try:
            r = subprocess.run(
                ["findmnt", "-n", "-o", "SOURCE", path],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            live[path] = (r.stdout or "").strip()
        except Exception:
            live[path] = ""

    def on_sdb(src: str) -> bool:
        return bool(src) and ("/dev/sdb" in src or src.startswith("sdb"))

    used_pg = on_sdb(live.get("/var/lib/postgresql", "")) or on_sdb(live.get("/", ""))
    # postgres data on / means sda, not automatically sdb
    used_pg = any(on_sdb(v) for k, v in live.items() if "postgresql" in k) or False
    # re-check: if / is sda5 and pg lives under /, sdb not used
    used_system = on_sdb(live.get("/", ""))
    used_docs = on_sdb(live.get("/data", ""))
    used_crm = on_sdb(live.get("/opt/CRM_Streamlit", ""))
    unused = len(mount_points) == 0 and not used_pg and not used_docs and not used_crm and not used_system

    role = "UNUSED_LEGACY_NTFS_PARTITIONS" if unused and filesystems and all(
        f.lower() == "ntfs" for f in filesystems if f
    ) else ("MOUNTED" if mount_points else ("UNUSED" if unused else "UNKNOWN"))

    return {
        "device": "/dev/sdb",
        "SDB_PARTITIONS": partitions,
        "SDB_MOUNT_POINTS": mount_points,
        "SDB_FILESYSTEMS": sorted(set(filesystems)),
        "IS_SDB_USED_BY_POSTGRES": False if unused else used_pg,
        "IS_SDB_USED_BY_CRM": used_crm,
        "IS_SDB_USED_BY_DOCUMENT_STORAGE": used_docs,
        "IS_SDB_USED_BY_SYSTEM": used_system,
        "IS_SDB_CURRENTLY_UNUSED": unused,
        "SDB_DATA_ROLE": role,
        "live_sources": live,
    }
