"""SMART / NVMe health probes — soft-fail to UNAVAILABLE (no fake Health%)."""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from src.services.system_health_config import FAKE_DISK_HEALTH_PERCENT

assert FAKE_DISK_HEALTH_PERCENT is False


def _run(cmd: List[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _smartctl_base(dev: str) -> List[str]:
    """Prefer direct access; fall back to sudo -n without expanding privileges policy."""
    smartctl = shutil.which("smartctl")
    if not smartctl:
        return []
    # try without sudo
    probe = _run([smartctl, "-i", dev], timeout=8)
    if probe.returncode == 0 and "Permission denied" not in (probe.stderr or ""):
        return [smartctl]
    # existing host may allow passwordless sudo for this user — do not rewrite sudoers here
    return ["sudo", "-n", smartctl]


def collect_smart_for_device(dev: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "device": dev,
        "available": False,
        "status": "UNAVAILABLE",
        "overall": None,
        "temperature_c": None,
        "power_on_hours": None,
        "reallocated_sectors": None,
        "pending_sectors": None,
        "offline_uncorrectable": None,
        "reported_uncorrect": None,
        "crc_errors": None,
        "wear": None,
        "error_summary": None,
        "transport_hint": "ata",
    }
    base = _smartctl_base(dev)
    if not base:
        out["error_summary"] = "smartctl not installed"
        return out
    health = _run(base + ["-H", dev])
    attrs = _run(base + ["-A", dev])
    info = _run(base + ["-i", dev])
    blob = "\n".join([health.stdout or "", attrs.stdout or "", info.stdout or "", health.stderr or ""])
    if "Permission denied" in blob or health.returncode > 1 and "Permission denied" in (health.stderr or ""):
        out["error_summary"] = "SMART permission denied (safe UNAVAILABLE)"
        return out
    if "No such device" in blob or "failed to open" in blob.lower():
        out["error_summary"] = "device open failed"
        return out

    out["available"] = True
    if "PASSED" in (health.stdout or ""):
        out["overall"] = "PASSED"
        out["status"] = "OK"
    elif "FAILED" in (health.stdout or ""):
        out["overall"] = "FAILED"
        out["status"] = "CRITICAL"
    else:
        out["overall"] = "UNKNOWN"
        out["status"] = "WARNING"

    def attr_raw(name: str) -> Optional[int]:
        for line in (attrs.stdout or "").splitlines():
            if name in line:
                parts = line.split()
                if len(parts) >= 10:
                    raw_str = " ".join(parts[9:])
                    nums = re.findall(r"-?\d+", raw_str)
                    if nums:
                        return int(nums[0])
        return None

    def attr_norm(name: str) -> Optional[int]:
        for line in (attrs.stdout or "").splitlines():
            if name in line:
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        return int(parts[3])
                    except Exception:
                        return None
        return None

    temp = attr_raw("Temperature_Celsius")
    if temp is None:
        temp = attr_raw("Airflow_Temperature_Cel")
    out["temperature_c"] = temp
    out["power_on_hours"] = attr_raw("Power_On_Hours")
    out["reallocated_sectors"] = attr_raw("Reallocated_Sector_Ct")
    out["pending_sectors"] = attr_raw("Current_Pending_Sector")
    out["offline_uncorrectable"] = attr_raw("Offline_Uncorrectable")
    out["reported_uncorrect"] = attr_raw("Reported_Uncorrect") or attr_raw("Uncorrectable_Error_Cnt")
    out["crc_errors"] = attr_raw("UDMA_CRC_Error_Count") or attr_raw("CRC_Error_Count")

    # Samsung Wear_Leveling_Count: normalized VALUE often ≈ remaining life %
    wlc_norm = attr_norm("Wear_Leveling_Count")
    wlc_raw = attr_raw("Wear_Leveling_Count")
    if wlc_norm is not None:
        out["wear"] = {
            "attribute": "Wear_Leveling_Count",
            "normalized": wlc_norm,
            "raw": wlc_raw,
            "percent_used_estimate": max(0, min(100, 100 - wlc_norm)),
            "estimate_marked": "DERIVED_FROM_100_MINUS_NORMALIZED",
        }
    out["status"] = derive_physical_status(out)
    return out


def derive_physical_status(d: Dict[str, Any]) -> str:
    """Combine SMART overall + sector errors + temp + NVMe signals.

    SMART PASSED alone must NOT hide realloc/pending/media errors.
    """
    from src.services.system_health_config import (
        DISK_TEMP_CRIT_C,
        DISK_TEMP_WARN_C,
        NVME_PCT_USED_CRIT,
        NVME_PCT_USED_WARN,
        SMART_OVERALL_PASS_HIDES_SECTOR_ERRORS,
    )

    assert SMART_OVERALL_PASS_HIDES_SECTOR_ERRORS is False
    if not d.get("available"):
        return "UNAVAILABLE"
    if d.get("overall") == "FAILED":
        return "CRITICAL"
    if (d.get("critical_warning") or 0) != 0:
        return "CRITICAL"
    spare = d.get("available_spare")
    thr = d.get("available_spare_threshold")
    if spare is not None and thr is not None and spare < thr:
        return "CRITICAL"
    pct = d.get("percentage_used")
    if pct is None and isinstance(d.get("wear"), dict):
        pct = d["wear"].get("percent_used_estimate")
    if pct is not None and pct >= NVME_PCT_USED_CRIT:
        return "CRITICAL"
    media = d.get("media_errors") or 0
    if media > 0:
        return "CRITICAL"
    temp = d.get("temperature_c")
    if temp is not None and temp >= DISK_TEMP_CRIT_C:
        return "CRITICAL"

    warn = False
    for key in ("reallocated_sectors", "pending_sectors", "offline_uncorrectable", "reported_uncorrect"):
        val = d.get(key)
        if val is not None and val > 0:
            warn = True
    if pct is not None and pct >= NVME_PCT_USED_WARN:
        warn = True
    if temp is not None and temp >= DISK_TEMP_WARN_C:
        warn = True
    if d.get("overall") not in ("PASSED", None) and d.get("kind") == "ata":
        warn = True
    if warn:
        return "WARNING"
    if d.get("overall") == "PASSED" or d.get("kind") == "nvme":
        return "OK"
    return "WARNING"


def disk_summary_counts(disks: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"OK": 0, "WARNING": 0, "CRITICAL": 0, "UNAVAILABLE": 0}
    for d in disks:
        st = d.get("status") or derive_physical_status(d)
        d["status"] = st
        counts[st] = counts.get(st, 0) + 1
    return counts


def collect_nvme_smart(dev: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "device": dev,
        "available": False,
        "status": "UNAVAILABLE",
        "critical_warning": None,
        "temperature_c": None,
        "available_spare": None,
        "available_spare_threshold": None,
        "percentage_used": None,
        "power_cycles": None,
        "power_on_hours": None,
        "unsafe_shutdowns": None,
        "media_errors": None,
        "num_err_log_entries": None,
    }
    nvme = shutil.which("nvme")
    if not nvme:
        out["error_summary"] = "nvme CLI not installed"
        return out
    cmd = [nvme, "smart-log", dev]
    r = _run(cmd)
    if r.returncode != 0:
        r = _run(["sudo", "-n", nvme, "smart-log", dev])
    if r.returncode != 0:
        out["error_summary"] = (r.stderr or r.stdout or "nvme smart-log failed")[:200]
        return out
    text = r.stdout or ""
    out["available"] = True

    def grab(key: str) -> Optional[int]:
        for line in text.splitlines():
            if key in line.lower() or key.replace("_", " ") in line.lower():
                nums = re.findall(r"\d+", line.split(":")[-1])
                if nums:
                    return int(nums[0])
        return None

    # nvme-cli keys vary slightly
    mapping = {
        "critical_warning": ("critical_warning",),
        "temperature_c": ("temperature",),
        "available_spare": ("available_spare",),
        "available_spare_threshold": ("available_spare_threshold",),
        "percentage_used": ("percentage_used",),
        "power_cycles": ("power_cycles",),
        "power_on_hours": ("power_on_hours",),
        "unsafe_shutdowns": ("unsafe_shutdowns",),
        "media_errors": ("media_errors",),
        "num_err_log_entries": ("num_err_log_entries",),
    }
    for field, keys in mapping.items():
        for k in keys:
            for line in text.splitlines():
                if k.replace("_", " ") in line.lower() or k in line.lower():
                    nums = re.findall(r"\d+", line.split(":")[-1])
                    if nums:
                        val = int(nums[0])
                        if field == "temperature_c" and val > 200:
                            val = val  # already Celsius in modern nvme-cli
                        out[field] = val
                        break
            if out[field] is not None:
                break

    cw = out.get("critical_warning") or 0
    pct = out.get("percentage_used")
    spare = out.get("available_spare")
    thr = out.get("available_spare_threshold")
    if cw != 0:
        out["status"] = "CRITICAL"
    elif spare is not None and thr is not None and spare < thr:
        out["status"] = "CRITICAL"
    elif pct is not None and pct >= 100:
        out["status"] = "CRITICAL"
    elif pct is not None and pct >= 90:
        out["status"] = "WARNING"
    else:
        out["status"] = "OK"
    out["status"] = derive_physical_status(out)
    # Do NOT invent overall Health percent from wear (FAKE_DISK_HEALTH_PERCENT=NO)
    return out


def collect_all_disk_health(block_devices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = []
    for d in block_devices:
        dev = d.get("device")
        if not dev:
            continue
        transport = (d.get("transport") or "").lower()
        name = d.get("name") or ""
        if name.startswith("nvme") or transport == "nvme":
            smart = collect_nvme_smart(dev)
            smart["kind"] = "nvme"
        else:
            smart = collect_smart_for_device(dev)
            smart["kind"] = "ata"
        smart["model"] = d.get("model")
        smart["capacity_b"] = d.get("capacity_b")
        smart["transport"] = d.get("transport")
        smart["mount_points"] = d.get("mount_points")
        smart["status"] = derive_physical_status(smart)
        results.append(smart)
    return results
