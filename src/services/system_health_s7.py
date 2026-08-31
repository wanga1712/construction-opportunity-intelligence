"""S7 remote health collection via SSH (collector process only)."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.services.system_health_config import (
    HOST_S7,
    S7_COLLECTION_TIMEOUT,
    S7_COMMAND_TIMEOUT,
    S7_CONNECT_TIMEOUT,
    S7_SOURCE_COLLECTORS,
    S7_SSH_IDENTITY,
    S7_SSH_TARGET,
)

# Remote script: read-only, no mutations, prints one JSON object.
_REMOTE_PY = r"""
import json, os, re, socket, subprocess, time
from pathlib import Path

def sh(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout or "", r.stderr or "", r.returncode
    except Exception as e:
        return "", str(e), 1

def loadavg():
    try:
        a,b,c = os.getloadavg()
        return a,b,c
    except Exception:
        return None, None, None

def mem():
    m={}
    for line in open("/proc/meminfo"):
        k,v=line.split(":",1)
        m[k]=int(v.split()[0])*1024
    total=m.get("MemTotal",0); avail=m.get("MemAvailable", m.get("MemFree",0))
    st=m.get("SwapTotal",0); sf=m.get("SwapFree",0)
    return {
        "ram_total_b": total, "ram_used_b": max(0,total-avail), "ram_available_b": avail,
        "ram_used_pct": round(100.0*(total-avail)/total,1) if total else None,
        "swap_total_b": st, "swap_used_b": max(0,st-sf),
        "swap_used_pct": round(100.0*(st-sf)/st,1) if st else 0.0,
    }

def cpu_pct():
    def read():
        line=open("/proc/stat").readline().split()
        vals=list(map(float,line[1:]))
        return vals
    a=read(); time.sleep(0.2); b=read()
    idle_a=a[3]+(a[4] if len(a)>4 else 0); idle_b=b[3]+(b[4] if len(b)>4 else 0)
    dt=sum(b)-sum(a); di=idle_b-idle_a
    if dt<=0: return None, "NOT_AVAILABLE"
    return round((1-di/dt)*100,1), "OK"

def fs_stat(mount):
    try:
        u=os.statvfs(mount)
    except Exception:
        return None
    total=u.f_frsize*u.f_blocks; free=u.f_frsize*u.f_bavail; used=total-free
    it=u.f_files; iff=u.f_favail; iu=max(0,it-iff) if it else 0
    src,_,_=sh(f"findmnt -n -o SOURCE,FSTYPE {mount}")
    parts=src.strip().split()
    return {
        "mount": mount, "device": parts[0] if parts else None, "fstype": parts[1] if len(parts)>1 else None,
        "total_b": total, "used_b": used, "free_b": free,
        "used_pct": round(100*used/total,1) if total else None,
        "inodes_total": it, "inodes_used": iu, "inodes_free": iff,
        "inodes_used_pct": round(100*iu/it,1) if it else None, "readonly": False,
    }

def cpu_temp_bundle():
    import shutil
    sensors_ok=bool(shutil.which("sensors"))
    thermal_ok=bool(list(Path("/sys/class/thermal").glob("thermal_zone*")))
    package=None; core_max=None; source=None
    if sensors_ok:
        out,_,_=sh("sensors -u 2>/dev/null")
        label=""; cores=[]
        for line in out.splitlines():
            if line and not line[0].isspace() and line.strip().endswith(":"):
                label=line.strip().rstrip(":"); continue
            if "_input:" in line:
                try: val=float(line.split(":")[-1].strip())
                except: continue
                if not (0<val<125): continue
                if "Package" in label: package=val; source="sensors:"+label
                elif label.startswith("Core"): cores.append(val)
        if cores:
            core_max=max(cores)
            if package is None: source="sensors:Core max"
    if package is None and core_max is None and thermal_ok:
        for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            try:
                ztype=(zone/"type").read_text().strip()
                c=float((zone/"temp").read_text().strip())/1000.0
            except Exception:
                continue
            if c<=0 or c>125: continue
            # accept x86_pkg_temp/coretemp/k10temp; also acpitz only as last resort marked system
            if ztype in ("x86_pkg_temp","coretemp","k10temp"):
                package=c; source="sysfs:"+ztype; break
        if package is None:
            # last resort: any thermal_zone in plausible CPU range, mark source
            for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
                try:
                    ztype=(zone/"type").read_text().strip()
                    c=float((zone/"temp").read_text().strip())/1000.0
                except Exception:
                    continue
                if 20 < c < 105 and ztype:
                    package=c; source="sysfs:"+ztype; break
    display = package if package is not None else core_max
    return {
        "cpu_package_temp_c": package,
        "cpu_core_max_temp_c": core_max,
        "display_cpu_temp_c": display,
        "cpu_temp_source": source,
        "S7_SENSORS_AVAILABLE": sensors_ok,
        "S7_THERMAL_SYSFS_AVAILABLE": thermal_ok,
        "disk_temperatures": [],
    }

def unit(name):
    act,_,_=sh(f"systemctl is-active {name}"); en,_,_=sh(f"systemctl is-enabled {name}")
    props,_,_=sh(f"systemctl show {name} -p Type -p SubState -p Result -p ActiveEnterTimestamp -p InactiveExitTimestamp -p ExecMainStartTimestamp")
    d={}
    for line in props.splitlines():
        if "=" in line:
            k,v=line.split("=",1); d[k]=v
    return {"unit": name, "active": act.strip(), "enabled": en.strip(),
            "type": d.get("Type",""), "substate": d.get("SubState",""), "result": d.get("Result",""),
            "activeentertimestamp": d.get("ActiveEnterTimestamp",""),
            "inactiveexittimestamp": d.get("InactiveExitTimestamp",""),
            "execmainstarttimestamp": d.get("ExecMainStartTimestamp","")}

def journal_last(unit):
    out,_,rc=sh(f"journalctl -u {unit} -n 1 --no-pager -o short-iso 2>/dev/null")
    line=(out or "").strip().splitlines()[-1] if (out or "").strip() else ""
    # parse leading ISO timestamp if present
    m=re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+\-]\d{2}:\d{2})", line)
    return {"raw": line[:240], "ts": m.group(1) if m else None}

def blocks():
    out,_,_=sh("lsblk -J -b -o NAME,SIZE,TYPE,TRAN,MODEL,FSTYPE,MOUNTPOINTS")
    try: data=json.loads(out or "{}")
    except: return []
    disks=[]
    for node in data.get("blockdevices") or []:
        if node.get("type")!="disk": continue
        mounts=[]; fss=[]
        def walk(n):
            mp=n.get("mountpoints") or []
            if isinstance(mp,list):
                mounts.extend([m for m in mp if m])
            if n.get("fstype"): fss.append(n.get("fstype"))
            for ch in n.get("children") or []: walk(ch)
        walk(node)
        disks.append({"device": f"/dev/{node.get('name')}", "name": node.get("name"),
            "model": (node.get("model") or "").strip() or None, "capacity_b": int(node.get("size") or 0),
            "transport": node.get("tran"), "filesystems": sorted(set(fss)), "mount_points": sorted(set(mounts))})
    return disks

def net():
    rows=[]
    for line in open("/proc/net/dev").read().splitlines()[2:]:
        if ":" not in line: continue
        name, rest=line.split(":",1); name=name.strip()
        if name=="lo": continue
        p=rest.split()
        oper=Path(f"/sys/class/net/{name}/operstate").read_text().strip() if Path(f"/sys/class/net/{name}/operstate").exists() else "unknown"
        rows.append({"iface": name, "operstate": oper, "rx_bytes": int(p[0]), "tx_bytes": int(p[8]),
            "rx_errors": int(p[2]), "tx_errors": int(p[10]), "rx_dropped": int(p[3]), "tx_dropped": int(p[11])})
    return rows

boot=None
try:
    up=float(open("/proc/uptime").read().split()[0]); boot=time.time()-up
except: pass
usage, usage_st=cpu_pct()
l1,l5,l15=loadavg()
fwd=journal_last("tendermonitor-eis-parser.service")
bwd=journal_last("tendermonitor-eis-parser-backward.service")
daily=unit("tendermonitor-daily-migration.service")
mon=unit("tendermonitor-monitoring.service")
# latest activity among known parser journals
cands=[x for x in [fwd.get("ts"), bwd.get("ts")] if x]
latest=max(cands) if cands else None
age=None
if latest:
    try:
        # fromisoformat needs careful offset
        ts=latest
        # python 3.10+
        from datetime import datetime
        dt=datetime.fromisoformat(ts)
        age=(datetime.now(dt.tzinfo)-dt).total_seconds() if dt.tzinfo else None
    except Exception:
        age=None

pg_ok=False
try:
    s=socket.create_connection(("127.0.0.1",5432),1.5); s.close(); pg_ok=True
except: pass
pg_ver,_,_=sh("psql --version 2>/dev/null")
tb=cpu_temp_bundle()
blk=blocks()

out={
  "host_id": "S7",
  "hostname": socket.gethostname(),
  "kernel": open("/proc/version").read().strip()[:120],
  "boot_time": boot,
  "cpu": {"usage_pct": usage, "usage_pct_status": usage_st, "load_1": l1, "load_5": l5, "load_15": l15,
          "cores": os.cpu_count(), "temp_c": tb.get("display_cpu_temp_c"), "temp_source": tb.get("cpu_temp_source"), "model": None},
  "memory": mem(),
  "filesystems": [x for x in [fs_stat("/")] if x],
  "block_devices": blk,
  "physical_disks_discovered": len(blk),
  "temperatures": tb,
  "S7_SENSORS_AVAILABLE": tb.get("S7_SENSORS_AVAILABLE"),
  "S7_THERMAL_SYSFS_AVAILABLE": tb.get("S7_THERMAL_SYSFS_AVAILABLE"),
  "network": net(),
  "postgres": {"reachable_127_5432": pg_ok, "version": (pg_ver or "").strip() or None,
               "service_active": unit("postgresql.service")["active"]=="active" or unit("postgresql@17-main.service")["active"]=="active",
               "ui_status": "OK" if pg_ok else "CRITICAL"},
  "source_collectors": [unit(u) for u in [
      "tendermonitor-eis-parser.service","tendermonitor-eis-parser-backward.service",
      "tendermonitor-daily-migration.timer","tendermonitor-monitoring.timer"]],
  "source_freshness": {
      "LATEST_SOURCE_UPDATE": latest,
      "SOURCE_AGE_SEC": age,
      "LAST_FORWARD_PARSER_ACTIVITY": fwd.get("ts"),
      "LAST_BACKWARD_PARSER_ACTIVITY": bwd.get("ts"),
      "LAST_DAILY_MIGRATION": daily.get("execmainstarttimestamp") or None,
      "LAST_MONITORING_RUN": mon.get("execmainstarttimestamp") or None,
      "unsupported": [],
  },
  "disk_health": [],
  "collection_errors": [],
}
# SMART soft if available
import shutil
if shutil.which("smartctl"):
  for d in out["block_devices"]:
    dev=d["device"]
    h,_,_=sh(f"sudo -n smartctl -H {dev} 2>/dev/null || smartctl -H {dev} 2>/dev/null")
    a,_,_=sh(f"sudo -n smartctl -A {dev} 2>/dev/null || smartctl -A {dev} 2>/dev/null")
    status="UNAVAILABLE"; overall=None
    if "PASSED" in h: overall="PASSED"; status="OK"
    elif "FAILED" in h: overall="FAILED"; status="CRITICAL"
    def raw(name):
      for line in (a or "").splitlines():
        if name in line:
          parts=line.split()
          if len(parts)>=10:
            nums=re.findall(r"-?\d+", " ".join(parts[9:]))
            if nums: return int(nums[0])
      return None
    realloc=raw("Reallocated_Sector_Ct"); pending=raw("Current_Pending_Sector")
    uncorr=raw("Offline_Uncorrectable"); temp=raw("Temperature_Celsius") or raw("Airflow_Temperature_Cel")
    if (realloc or 0)>0 or (pending or 0)>0 or (uncorr or 0)>0: status="WARNING" if status!="CRITICAL" else status
    if temp and temp>=60: status="CRITICAL"
    elif temp and temp>=50: status="WARNING" if status=="OK" else status
    out["disk_health"].append({"device":dev,"model":d.get("model"),"overall":overall,"status":status,
      "temperature_c":temp,"reallocated_sectors":realloc,"pending_sectors":pending,
      "offline_uncorrectable":uncorr,"available": overall is not None, "kind":"ata",
      "mount_points": d.get("mount_points"), "capacity_b": d.get("capacity_b"), "transport": d.get("transport")})
out["smart_accessible_devices"]=sum(1 for x in out["disk_health"] if x.get("available"))
out["temperatures"]["disk_temperatures"]=[{"device":x.get("device"),"model":x.get("model"),"temp_c":x.get("temperature_c")} for x in out["disk_health"] if x.get("temperature_c") is not None]
print(json.dumps(out, ensure_ascii=False))
"""


def _ssh_base() -> List[str]:
    return [
        "ssh",
        "-i",
        S7_SSH_IDENTITY,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={S7_CONNECT_TIMEOUT}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        S7_SSH_TARGET,
    ]


def check_s7_reachable() -> bool:
    import socket
    # Try port 22 (SSH) first
    try:
        s = socket.create_connection(("10.8.0.7", 22), timeout=2.0)
        s.close()
        return True
    except Exception:
        pass
    # Try ping as fallback
    try:
        import subprocess
        r = subprocess.run(["ping", "-c", "1", "-W", "2", "10.8.0.7"], capture_output=True, timeout=3)
        return r.returncode == 0
    except Exception:
        return False


def collect_s7_host() -> Dict[str, Any]:
    """SSH to S7 and collect metrics. Soft-fail → UNREACHABLE payload."""
    base = {
        "host_id": HOST_S7,
        "reachable": False,
        "connectivity": "unavailable",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "collection_errors": [],
        "alerts": [],
        "overall_status": "UNREACHABLE",
    }
    cmd = _ssh_base() + ["python3", "-"]
    try:
        r = subprocess.run(
            cmd,
            input=_REMOTE_PY,
            capture_output=True,
            text=True,
            timeout=S7_COLLECTION_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        reachable = check_s7_reachable()
        base["reachable"] = reachable
        base["connectivity"] = "collector_failed" if reachable else "unavailable"
        base["overall_status"] = "WARNING" if reachable else "UNREACHABLE"
        base["collection_errors"].append("S7 collection timeout")
        return base
    except Exception as exc:
        reachable = check_s7_reachable()
        base["reachable"] = reachable
        base["connectivity"] = "collector_failed" if reachable else "unavailable"
        base["overall_status"] = "WARNING" if reachable else "UNREACHABLE"
        base["collection_errors"].append(str(exc))
        return base

    if r.returncode != 0:
        reachable = check_s7_reachable()
        base["reachable"] = reachable
        base["connectivity"] = "collector_failed" if reachable else "unavailable"
        base["overall_status"] = "WARNING" if reachable else "UNREACHABLE"
        err = (r.stderr or r.stdout or "ssh failed")[:500]
        base["collection_errors"].append(err)
        return base

    text = (r.stdout or "").strip()
    # last JSON line
    try:
        payload = json.loads(text.splitlines()[-1])
    except Exception as exc:
        reachable = check_s7_reachable()
        base["reachable"] = reachable
        base["connectivity"] = "collector_failed" if reachable else "unavailable"
        base["overall_status"] = "WARNING" if reachable else "UNREACHABLE"
        base["collection_errors"].append(f"json parse: {exc}")
        return base

    payload["reachable"] = True
    payload["connectivity"] = "reachable"
    payload["collected_at"] = datetime.now(timezone.utc).isoformat()
    payload["host_id"] = HOST_S7
    # enrich collectors ui_status
    for c in payload.get("source_collectors") or []:
        act = c.get("active")
        unit = c.get("unit") or ""
        if unit.endswith(".timer"):
            c["expectation"] = "TIMER"
            c["ui_status"] = "OK" if act == "active" else "WARNING"
        else:
            c["expectation"] = "LONG_RUNNING"
            c["ui_status"] = "OK" if act == "active" else "CRITICAL"
            c["health_model"] = "LONG_RUNNING"
    return payload


def s7_timeouts() -> Dict[str, int]:
    return {
        "S7_CONNECT_TIMEOUT": S7_CONNECT_TIMEOUT,
        "S7_COMMAND_TIMEOUT": S7_COMMAND_TIMEOUT,
        "S7_COLLECTION_TIMEOUT": S7_COLLECTION_TIMEOUT,
        "S7_SOURCE_COLLECTORS": list(S7_SOURCE_COLLECTORS),
    }
