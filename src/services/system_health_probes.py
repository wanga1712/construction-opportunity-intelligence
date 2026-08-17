"""OS probes via /proc, sysfs, and optional tools — no Streamlit."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.services.system_health_config import IMPORTANT_MOUNTS_S13 as IMPORTANT_MOUNTS

try:
    import psutil  # type: ignore

    PSUTIL_AVAILABLE = True
except Exception:
    psutil = None  # type: ignore
    PSUTIL_AVAILABLE = False


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def capability_audit() -> Dict[str, Any]:
    thermal = list(Path("/sys/class/thermal").glob("thermal_zone*"))
    return {
        "PSUTIL_AVAILABLE": PSUTIL_AVAILABLE,
        "SMARTCTL_AVAILABLE": bool(_which("smartctl")),
        "NVME_CLI_AVAILABLE": bool(_which("nvme")),
        "SENSORS_AVAILABLE": bool(_which("sensors")),
        "THERMAL_SYSFS_AVAILABLE": bool(thermal),
        "LSBLK_AVAILABLE": bool(_which("lsblk")),
        "FINDMNT_AVAILABLE": bool(_which("findmnt")),
    }


def _read_text(path: str) -> Optional[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None


def host_identity() -> Dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "kernel": _read_text("/proc/version") or os.uname().release,
        "boot_time": _boot_time(),
    }


def _boot_time() -> Optional[float]:
    if PSUTIL_AVAILABLE:
        try:
            return float(psutil.boot_time())
        except Exception:
            pass
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        return time.time() - uptime
    except Exception:
        return None


def cpu_model() -> Optional[str]:
    raw = _read_text("/proc/cpuinfo") or ""
    for line in raw.splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[-1].strip()
    return None


def collect_cpu(*, last_valid: Optional[float] = None) -> Dict[str, Any]:
    """CPU metrics. Never publish invalid sample as 0.0%."""
    from src.services.system_health_config import INVALID_CPU_SAMPLE_DISPLAYED_AS_ZERO

    global _last_valid_cpu_pct
    assert INVALID_CPU_SAMPLE_DISPLAYED_AS_ZERO is False
    load1 = load5 = load15 = None
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        pass
    cores = os.cpu_count() or 0
    freq_mhz = None
    if PSUTIL_AVAILABLE:
        try:
            f = psutil.cpu_freq()
            if f:
                freq_mhz = f.current
        except Exception:
            pass
    usage = _cpu_percent_sample()
    total = usage.get("total")
    status = "OK"
    if total is None:
        cached = last_valid if last_valid is not None else _last_valid_cpu_pct
        if cached is not None:
            total = cached
            status = "CACHED_LAST_VALID"
        else:
            status = "NOT_AVAILABLE"
            total = None
    else:
        _last_valid_cpu_pct = float(total)
    return {
        "model": cpu_model(),
        "cores": cores,
        "threads": cores,
        "usage_pct": total,
        "usage_pct_status": status,
        "per_core_pct": usage.get("per_core"),
        "load_1": load1,
        "load_5": load5,
        "load_15": load15,
        "freq_mhz": freq_mhz,
        "temp_c": collect_cpu_temp_c(),
    }


_prev_cpu: Optional[Tuple[float, ...]] = None
_prev_cpu_cores: Optional[List[Tuple[float, ...]]] = None
_last_valid_cpu_pct: Optional[float] = None


def _parse_cpu_line(line: str) -> Tuple[float, ...]:
    parts = line.split()
    vals = [float(x) for x in parts[1:]]
    return tuple(vals)


def _cpu_percent_sample(interval: float = 0.15) -> Dict[str, Any]:
    """Sample /proc/stat twice for non-zero utilization."""
    global _prev_cpu, _prev_cpu_cores

    def read_all():
        lines = Path("/proc/stat").read_text().splitlines()
        total = _parse_cpu_line(lines[0])
        cores = [_parse_cpu_line(ln) for ln in lines[1:] if ln.startswith("cpu") and ln[3:4].isdigit()]
        return total, cores

    def pct(a, b):
        idle_a = a[3] + (a[4] if len(a) > 4 else 0)
        idle_b = b[3] + (b[4] if len(b) > 4 else 0)
        total_a = sum(a)
        total_b = sum(b)
        dt = total_b - total_a
        di = idle_b - idle_a
        if dt <= 0:
            return None
        return round(max(0.0, min(100.0, (1.0 - di / dt) * 100.0)), 1)

    t1, c1 = read_all()
    time.sleep(max(interval, 0.35))
    t2, c2 = read_all()
    per = []
    for a, b in zip(c1, c2):
        p = pct(a, b)
        if p is not None:
            per.append(p)
    return {"total": pct(t1, t2), "per_core": per}


def collect_cpu_temp_c() -> Optional[float]:
    """Prefer sensors coretemp Package; else thermal_zone with sensible type."""
    sensors = _which("sensors")
    if sensors:
        try:
            out = subprocess.run(
                [sensors, "-u"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout
            label = ""
            package = None
            core_vals = []
            for line in out.splitlines():
                if line and not line[0].isspace() and line.strip().endswith(":"):
                    label = line.strip().rstrip(":")
                    continue
                if "_input:" not in line:
                    continue
                try:
                    val = float(line.split(":")[-1].strip())
                except Exception:
                    continue
                if not (0 < val < 120):
                    continue
                if "Package" in label:
                    package = val
                elif label.startswith("Core"):
                    core_vals.append(val)
            if package is not None:
                return package
            if core_vals:
                return max(core_vals)
        except Exception:
            pass
    # sysfs: prefer x86_pkg_temp / coretemp — do not invent from bad ACPI alone
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        ztype = _read_text(str(zone / "type")) or ""
        raw = _read_text(str(zone / "temp"))
        if not raw:
            continue
        try:
            c = float(raw) / 1000.0
        except Exception:
            continue
        if c <= 0 or c > 125:
            continue
        if ztype in ("x86_pkg_temp", "coretemp", "k10temp"):
            return c
    return None


def collect_memory() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        parts = v.strip().split()
        try:
            mem[k] = int(parts[0]) * 1024  # kB → bytes
        except Exception:
            pass
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", mem.get("MemFree", 0))
    used = max(0, total - available)
    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    info.update(
        {
            "ram_total_b": total,
            "ram_used_b": used,
            "ram_available_b": available,
            "ram_used_pct": round(100.0 * used / total, 1) if total else None,
            "swap_total_b": swap_total,
            "swap_used_b": swap_used,
            "swap_used_pct": round(100.0 * swap_used / swap_total, 1) if swap_total else 0.0,
        }
    )
    return info


def collect_filesystems() -> List[Dict[str, Any]]:
    rows = []
    seen = set()
    for mount in IMPORTANT_MOUNTS:
        st = _fs_stat(mount)
        if st:
            rows.append(st)
            seen.add(mount)
    # also include other local mounts (skip virtual)
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            src, mnt, fstype = parts[0], parts[1], parts[2]
            if mnt in seen:
                continue
            if fstype in ("proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "squashfs", "overlay"):
                continue
            if not mnt.startswith("/"):
                continue
            if src.startswith("/dev/") and mnt.count("/") <= 2:
                st = _fs_stat(mnt)
                if st:
                    rows.append(st)
                    seen.add(mnt)
    except Exception:
        pass
    return rows


def _fs_stat(mount: str) -> Optional[Dict[str, Any]]:
    try:
        u = os.statvfs(mount)
    except Exception:
        return None
    total = u.f_frsize * u.f_blocks
    free = u.f_frsize * u.f_bavail
    used = total - free
    inodes_total = u.f_files
    inodes_free = u.f_favail
    inodes_used = max(0, inodes_total - inodes_free) if inodes_total else 0
    src = fstype = opts = None
    try:
        out = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE,FSTYPE,OPTIONS", mount],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout.strip()
        if out:
            bits = out.split()
            src = bits[0] if bits else None
            fstype = bits[1] if len(bits) > 1 else None
            opts = bits[2] if len(bits) > 2 else None
    except Exception:
        pass
    ro = bool(opts and ("ro," in opts or opts == "ro" or ",ro" in opts))
    return {
        "mount": mount,
        "device": src,
        "fstype": fstype,
        "total_b": total,
        "used_b": used,
        "free_b": free,
        "used_pct": round(100.0 * used / total, 1) if total else None,
        "inodes_total": inodes_total,
        "inodes_used": inodes_used,
        "inodes_free": inodes_free,
        "inodes_used_pct": round(100.0 * inodes_used / inodes_total, 1) if inodes_total else None,
        "readonly": ro,
    }


def collect_block_devices() -> List[Dict[str, Any]]:
    if not _which("lsblk"):
        return []
    try:
        out = subprocess.run(
            [
                "lsblk",
                "-J",
                "-b",
                "-o",
                "NAME,SIZE,TYPE,TRAN,MODEL,FSTYPE,MOUNTPOINTS,PKNAME,SERIAL",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        data = __import__("json").loads(out.stdout or "{}")
    except Exception:
        return []
    disks = []
    for node in data.get("blockdevices") or []:
        if node.get("type") != "disk":
            continue
        mounts = []
        fss = []

        def walk(n, parent=None):
            mp = n.get("mountpoints") or n.get("mountpoint")
            if isinstance(mp, list):
                for m in mp:
                    if m:
                        mounts.append(m)
            elif mp:
                mounts.append(mp)
            if n.get("fstype"):
                fss.append(n.get("fstype"))
            for ch in n.get("children") or []:
                walk(ch, n.get("name"))

        walk(node)
        disks.append(
            {
                "device": f"/dev/{node.get('name')}",
                "name": node.get("name"),
                "model": (node.get("model") or "").strip() or None,
                "capacity_b": int(node.get("size") or 0),
                "transport": node.get("tran"),
                "serial": node.get("serial"),
                "filesystems": sorted(set(fss)),
                "mount_points": sorted(set(mounts)),
            }
        )
    return disks


_prev_disk_io: Optional[Dict[str, Tuple[int, int, int, int, float]]] = None
_prev_net_io: Optional[Dict[str, Tuple[int, int, int, int, int, int, float]]] = None


def collect_disk_io() -> Dict[str, Any]:
    global _prev_disk_io
    now = time.time()
    cur: Dict[str, Tuple[int, int, int, int, float]] = {}
    try:
        for line in Path("/proc/diskstats").read_text().splitlines():
            p = line.split()
            if len(p) < 14:
                continue
            name = p[2]
            if not name or name.startswith("loop") or name.startswith("ram"):
                continue
            # skip partitions for rates summary — keep whole disks (no digit suffix after sd/nvme)
            if name[-1].isdigit() and not name.startswith("nvme"):
                continue
            if "p" in name and name.startswith("nvme"):
                continue
            reads = int(p[3])
            read_sec = int(p[5]) * 512
            writes = int(p[7])
            write_sec = int(p[9]) * 512
            cur[name] = (reads, read_sec, writes, write_sec, now)
    except Exception:
        return {"devices": []}
    devices = []
    if _prev_disk_io:
        for name, vals in cur.items():
            prev = _prev_disk_io.get(name)
            if not prev:
                continue
            dt = vals[4] - prev[4]
            if dt <= 0:
                continue
            devices.append(
                {
                    "device": name,
                    "read_bps": (vals[1] - prev[1]) / dt,
                    "write_bps": (vals[3] - prev[3]) / dt,
                    "read_iops": (vals[0] - prev[0]) / dt,
                    "write_iops": (vals[2] - prev[2]) / dt,
                }
            )
    _prev_disk_io = cur
    return {"devices": devices}


def collect_network() -> List[Dict[str, Any]]:
    global _prev_net_io
    now = time.time()
    cur: Dict[str, Tuple[int, int, int, int, int, int, float]] = {}
    try:
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
        for line in lines:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            if name == "lo":
                continue
            p = rest.split()
            rx_b, rx_err, rx_drop = int(p[0]), int(p[2]), int(p[3])
            tx_b, tx_err, tx_drop = int(p[8]), int(p[10]), int(p[11])
            cur[name] = (rx_b, tx_b, rx_err, tx_err, rx_drop, tx_drop, now)
    except Exception:
        return []
    out = []
    for name, vals in cur.items():
        oper = _read_text(f"/sys/class/net/{name}/operstate") or "unknown"
        row = {
            "iface": name,
            "operstate": oper,
            "rx_bytes": vals[0],
            "tx_bytes": vals[1],
            "rx_errors": vals[2],
            "tx_errors": vals[3],
            "rx_dropped": vals[4],
            "tx_dropped": vals[5],
            "rx_bps": None,
            "tx_bps": None,
        }
        if _prev_net_io and name in _prev_net_io:
            prev = _prev_net_io[name]
            dt = vals[6] - prev[6]
            if dt > 0:
                row["rx_bps"] = (vals[0] - prev[0]) / dt
                row["tx_bps"] = (vals[1] - prev[1]) / dt
        out.append(row)
    _prev_net_io = cur
    return out


def collect_top_processes(limit: int = 8) -> Dict[str, List[Dict[str, Any]]]:
    """Top by CPU and RSS — name only, no full cmdline (secret-safe)."""
    procs = []
    for pid_dir in Path("/proc").iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            pid = int(pid_dir.name)
            comm = _read_text(str(pid_dir / "comm")) or "?"
            status = _read_text(str(pid_dir / "status")) or ""
            rss_kb = 0
            for ln in status.splitlines():
                if ln.startswith("VmRSS:"):
                    rss_kb = int(ln.split()[1])
                    break
            # cpu: use utime+stime ticks
            stat = _read_text(str(pid_dir / "stat"))
            cpu_ticks = 0
            if stat:
                # comm may contain spaces in parens — split after last ')'
                rparen = stat.rfind(")")
                fields = stat[rparen + 2 :].split()
                utime = int(fields[11])
                stime = int(fields[12])
                cpu_ticks = utime + stime
            procs.append({"pid": pid, "name": comm[:64], "rss_b": rss_kb * 1024, "cpu_ticks": cpu_ticks})
        except Exception:
            continue
    by_ram = sorted(procs, key=lambda p: p["rss_b"], reverse=True)[:limit]
    # CPU% approximation needs two samples — store ticks delta via module cache
    global _prev_proc_ticks, _prev_proc_ts
    now = time.time()
    by_cpu = []
    if "_prev_proc_ticks" in globals() and _prev_proc_ticks is not None and _prev_proc_ts:
        dt = now - _prev_proc_ts
        hz = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK")) if hasattr(os, "sysconf") else 100
        try:
            hz = os.sysconf("SC_CLK_TCK")
        except Exception:
            hz = 100
        scored = []
        for p in procs:
            prev = _prev_proc_ticks.get(p["pid"])
            if prev is None or dt <= 0:
                continue
            d_ticks = p["cpu_ticks"] - prev
            cpu_pct = max(0.0, (d_ticks / hz) / dt * 100.0)
            scored.append({**p, "cpu_pct": round(cpu_pct, 1), "ram_mb": round(p["rss_b"] / 1048576, 1)})
        by_cpu = sorted(scored, key=lambda x: x["cpu_pct"], reverse=True)[:limit]
    _prev_proc_ticks = {p["pid"]: p["cpu_ticks"] for p in procs}
    _prev_proc_ts = now
    for p in by_ram:
        p["ram_mb"] = round(p["rss_b"] / 1048576, 1)
        p.pop("cpu_ticks", None)
        p.pop("rss_b", None)
    for p in by_cpu:
        p.pop("cpu_ticks", None)
        p.pop("rss_b", None)
    return {"by_cpu": by_cpu, "by_ram": by_ram}


_prev_proc_ticks: Optional[Dict[int, int]] = None
_prev_proc_ts: Optional[float] = None
