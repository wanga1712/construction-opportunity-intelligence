"""Structured health alerts — host_id required."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.services.system_health_config import (
    CPU_TEMP_CRIT_C,
    CPU_TEMP_WARN_C,
    DISK_TEMP_CRIT_C,
    DISK_TEMP_WARN_C,
    DISK_USED_CRIT_PCT,
    DISK_USED_WARN_PCT,
    INODE_USED_CRIT_PCT,
    INODE_USED_WARN_PCT,
    NVME_PCT_USED_CRIT,
    NVME_PCT_USED_WARN,
    SUSTAINED_CPU_ALERT,
    SUSTAINED_CPU_MIN_SAMPLES,
    SUSTAINED_CPU_WARN_PCT,
)
from src.services.system_health_smart import derive_physical_status
from src.services.system_health_temps import temp_status


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _alert(
    *,
    host_id: str,
    level: str,
    source: str,
    target: str,
    message: str,
    observed: Any,
    threshold: Any,
    first_seen: Optional[str] = None,
) -> Dict[str, Any]:
    ts = _now_iso()
    assert host_id, "host_id required"
    return {
        "host_id": host_id,
        "level": level,
        "source": source,
        "device_or_service": target,
        "message": message,
        "observed": observed,
        "threshold": threshold,
        "first_seen": first_seen or ts,
        "last_seen": ts,
    }


def evaluate_host_alerts(
    host_id: str,
    host_snap: Dict[str, Any],
    prev_alerts: Optional[List[Dict[str, Any]]] = None,
    *,
    history_cpu: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    prev_map = {}
    for a in prev_alerts or []:
        if a.get("host_id") != host_id:
            continue
        key = (a.get("level"), a.get("source"), a.get("device_or_service"), a.get("message"))
        prev_map[key] = a

    def add(**kwargs):
        key = (kwargs["level"], kwargs["source"], kwargs["target"], kwargs["message"])
        old = prev_map.get(key)
        alerts.append(
            _alert(
                host_id=host_id,
                level=kwargs["level"],
                source=kwargs["source"],
                target=kwargs["target"],
                message=kwargs["message"],
                observed=kwargs.get("observed"),
                threshold=kwargs.get("threshold"),
                first_seen=(old or {}).get("first_seen"),
            )
        )

    if host_snap.get("connectivity") == "unavailable" or host_snap.get("reachable") is False:
        if host_id != "S13":
            add(
                level="WARNING",
                source="connectivity",
                target=host_id,
                message="host unreachable / collection failed",
                observed=host_snap.get("connectivity"),
                threshold="reachable",
            )
        return alerts

    for fs in host_snap.get("filesystems") or []:
        mount = fs.get("mount") or "?"
        used = fs.get("used_pct")
        if used is not None:
            if used >= DISK_USED_CRIT_PCT:
                add(level="CRITICAL", source="filesystem", target=mount, message="disk used critical", observed=used, threshold=DISK_USED_CRIT_PCT)
            elif used >= DISK_USED_WARN_PCT:
                add(level="WARNING", source="filesystem", target=mount, message="disk used warning", observed=used, threshold=DISK_USED_WARN_PCT)
        iu = fs.get("inodes_used_pct")
        if iu is not None:
            if iu >= INODE_USED_CRIT_PCT:
                add(level="CRITICAL", source="inodes", target=mount, message="inode used critical", observed=iu, threshold=INODE_USED_CRIT_PCT)
            elif iu >= INODE_USED_WARN_PCT:
                add(level="WARNING", source="inodes", target=mount, message="inode used warning", observed=iu, threshold=INODE_USED_WARN_PCT)

    cpu_temp = (host_snap.get("temperatures") or {}).get("display_cpu_temp_c")
    if cpu_temp is None:
        cpu_temp = (host_snap.get("cpu") or {}).get("temp_c")
    st = temp_status(cpu_temp, kind="cpu")
    if st == "CRITICAL":
        add(level="CRITICAL", source="temperature", target="cpu", message="CPU temperature critical", observed=cpu_temp, threshold=CPU_TEMP_CRIT_C)
    elif st == "WARNING":
        add(level="WARNING", source="temperature", target="cpu", message="CPU temperature warning", observed=cpu_temp, threshold=CPU_TEMP_WARN_C)

    if SUSTAINED_CPU_ALERT and history_cpu is not None:
        recent = [x for x in history_cpu if x is not None][-SUSTAINED_CPU_MIN_SAMPLES:]
        if len(recent) >= SUSTAINED_CPU_MIN_SAMPLES and all(x >= SUSTAINED_CPU_WARN_PCT for x in recent):
            add(
                level="WARNING",
                source="cpu",
                target="cpu",
                message="sustained CPU >=90%",
                observed=round(sum(recent) / len(recent), 1),
                threshold=SUSTAINED_CPU_WARN_PCT,
            )

    for d in host_snap.get("disk_health") or []:
        st = d.get("status") or derive_physical_status(d)
        d["status"] = st
        dev = d.get("device") or "?"
        is_legacy = (dev == "/dev/sdb" or dev == "sdb")
        if st == "CRITICAL" or d.get("overall") == "FAILED":
            lvl = "WARNING" if is_legacy else "CRITICAL"
            add(level=lvl, source="disk", target=dev, message="disk health CRITICAL", observed=st, threshold="OK")
        elif st == "WARNING":
            add(level="WARNING", source="disk", target=dev, message="disk health WARNING", observed=st, threshold="OK")
        pending = d.get("pending_sectors")
        if pending and pending > 0:
            add(level="WARNING", source="smart", target=dev, message="pending sectors > 0", observed=pending, threshold=0)
        realloc = d.get("reallocated_sectors")
        if realloc and realloc > 0:
            add(level="WARNING", source="smart", target=dev, message="reallocated sectors > 0", observed=realloc, threshold=0)

    for svc in host_snap.get("services") or []:
        if svc.get("ui_status") == "CRITICAL":
            add(
                level="CRITICAL",
                source="service",
                target=svc.get("unit") or "?",
                message=svc.get("message") or "service critical",
                observed=svc.get("active"),
                threshold="active",
            )

    for svc in host_snap.get("source_collectors") or []:
        if svc.get("ui_status") == "CRITICAL":
            add(
                level="CRITICAL",
                source="source_collector",
                target=svc.get("unit") or "?",
                message="source collector not active",
                observed=svc.get("active"),
                threshold="active",
            )

    pg = host_snap.get("postgres") or {}
    if pg.get("ui_status") == "CRITICAL":
        add(level="CRITICAL", source="postgres", target="postgresql", message="PostgreSQL not healthy", observed=pg.get("ui_status"), threshold="OK")

    crm = host_snap.get("crm_streamlit") or {}
    if crm.get("ui_status") == "CRITICAL":
        add(level="CRITICAL", source="crm", target="crm-streamlit", message="CRM Streamlit not healthy", observed=crm.get("ui_status"), threshold="OK")

    return alerts


def overall_status(alerts: List[Dict[str, Any]]) -> str:
    levels = {a.get("level") for a in alerts}
    if "CRITICAL" in levels:
        return "CRITICAL"
    if "WARNING" in levels:
        return "WARNING"
    if "UNREACHABLE" in levels:
        return "WARNING"
    return "OK"


def worst_status(*statuses: str) -> str:
    # UNREACHABLE is a host connectivity state → treated as WARNING for global rollup
    order = {
        "OK": 0,
        "INFO": 0,
        "PAUSED": 0,
        "CURRENT": 0,
        "WARNING": 1,
        "STALE": 1,
        "UNREACHABLE": 1,
        "CRITICAL": 2,
        "COLLECTOR_DOWN": 2,
    }
    worst = "OK"
    for s in statuses:
        if not s:
            continue
        if order.get(s, 0) > order.get(worst, 0):
            worst = s
    if worst == "UNREACHABLE":
        return "WARNING"
    return worst


# Back-compat alias used by older tests
def evaluate_alerts(snap: Dict[str, Any], prev_alerts: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    host_id = snap.get("host_id") or "S13"
    return evaluate_host_alerts(host_id, snap, prev_alerts)
