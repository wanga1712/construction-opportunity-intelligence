"""Temperature thresholds, normalization, and display status."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.services.system_health_config import (
    CPU_TEMP_CRIT_C,
    CPU_TEMP_WARN_C,
    DISK_TEMP_CRIT_C,
    DISK_TEMP_WARN_C,
)

S7_TEMP_FAKE_VALUE = False


def temp_status(temp_c: Optional[float], *, kind: str = "cpu") -> str:
    """UNKNOWN when missing — never treat unavailable as OK."""
    if temp_c is None:
        return "UNKNOWN"
    warn = CPU_TEMP_WARN_C if kind == "cpu" else DISK_TEMP_WARN_C
    crit = CPU_TEMP_CRIT_C if kind == "cpu" else DISK_TEMP_CRIT_C
    if temp_c >= crit:
        return "CRITICAL"
    if temp_c >= warn:
        return "WARNING"
    return "OK"


def normalize_host_temperatures(
    *,
    cpu_package: Optional[float] = None,
    cpu_core_max: Optional[float] = None,
    system_temp: Optional[float] = None,
    disk_temps: Optional[List[Dict[str, Any]]] = None,
    sensors_available: Optional[bool] = None,
    thermal_sysfs_available: Optional[bool] = None,
    cpu_temp_source: Optional[str] = None,
) -> Dict[str, Any]:
    assert S7_TEMP_FAKE_VALUE is False
    display = cpu_package if cpu_package is not None else cpu_core_max
    disks = []
    for d in disk_temps or []:
        t = d.get("temp_c")
        disks.append(
            {
                "device": d.get("device"),
                "model": d.get("model"),
                "temp_c": t,
                "status": temp_status(t, kind="disk"),
            }
        )
    return {
        "cpu_package_temp_c": cpu_package,
        "cpu_core_max_temp_c": cpu_core_max,
        "system_temp_c": system_temp,
        "display_cpu_temp_c": display,
        "display_cpu_temp_status": temp_status(display, kind="cpu"),
        "cpu_temp_source": cpu_temp_source,
        "disk_temperatures": disks,
        "S7_SENSORS_AVAILABLE": sensors_available,
        "S7_THERMAL_SYSFS_AVAILABLE": thermal_sysfs_available,
    }


def collect_local_temperature_bundle() -> Dict[str, Any]:
    """S13 local sensors → normalized bundle (no fake values)."""
    import shutil
    import subprocess
    from pathlib import Path

    package = None
    core_max = None
    system_temp = None
    source = None
    sensors_ok = bool(shutil.which("sensors"))
    thermal_ok = bool(list(Path("/sys/class/thermal").glob("thermal_zone*")))

    if sensors_ok:
        try:
            out = subprocess.run(
                ["sensors", "-u"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout
            label = ""
            cores: List[float] = []
            acpi_vals: List[float] = []
            in_acpi = False
            for line in out.splitlines():
                if line and not line[0].isspace() and line.strip().endswith(":"):
                    label = line.strip().rstrip(":")
                    in_acpi = label.startswith("acpitz") or "acpi" in label.lower()
                    continue
                if "_input:" not in line:
                    continue
                try:
                    val = float(line.split(":")[-1].strip())
                except Exception:
                    continue
                if not (0 < val < 125):
                    continue
                if "Package" in label:
                    package = val
                    source = f"sensors:{label}"
                elif label.startswith("Core"):
                    cores.append(val)
                elif in_acpi:
                    acpi_vals.append(val)
            if cores:
                core_max = max(cores)
                if package is None:
                    source = "sensors:Core max"
            if acpi_vals:
                system_temp = max(acpi_vals)
        except Exception:
            pass

    if package is None and core_max is None:
        for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            ztype = (zone / "type").read_text(encoding="utf-8", errors="replace").strip()
            try:
                c = float((zone / "temp").read_text().strip()) / 1000.0
            except Exception:
                continue
            if c <= 0 or c > 125:
                continue
            if ztype in ("x86_pkg_temp", "coretemp", "k10temp"):
                package = c
                source = f"sysfs:{ztype}"
                break

    return normalize_host_temperatures(
        cpu_package=package,
        cpu_core_max=core_max,
        system_temp=system_temp,
        sensors_available=sensors_ok,
        thermal_sysfs_available=thermal_ok,
        cpu_temp_source=source,
    )
