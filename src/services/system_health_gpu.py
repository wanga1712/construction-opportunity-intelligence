"""S13 GPU + Ollama probes for system health collector.

Never invent unsupported metrics as 0 — use None / N/A.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("system_health.gpu")

GPU_SAMPLE_INTERVAL_NOTE = "inherits FAST_INTERVAL_SEC (12s)"
BACKGROUND_GPU_COLLECTION = True
STREAMLIT_DIRECT_GPU_POLLING = False


def _run(cmd: List[str], timeout: float = 5.0) -> Optional[str]:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout)
    except Exception:
        return None


def collect_nvidia_gpu() -> Dict[str, Any]:
    """Return GPU telemetry via nvidia-smi. Unsupported fields stay None."""
    out: Dict[str, Any] = {
        "gpu_available": False,
        "gpu_vendor": None,
        "gpu_model": None,
        "gpu_count": None,
        "gpu_driver": None,
        "gpu_runtime": None,
        "gpu_util_percent": None,
        "gpu_vram_used_mb": None,
        "gpu_vram_total_mb": None,
        "gpu_vram_percent": None,
        "gpu_temp_c": None,
        "gpu_power_w": None,
        "gpu_power_limit_w": None,
        "gpu_fan_percent": None,
        "gpu_core_clock_mhz": None,
        "gpu_memory_clock_mhz": None,
        "gpu_processes": [],
        "collection_error": None,
    }
    q = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,count,utilization.gpu,memory.used,memory.total,"
            "temperature.gpu,power.draw,power.limit,fan.speed,clocks.gr,clocks.mem",
            "--format=csv,noheader,nounits",
        ]
    )
    if not q:
        out["collection_error"] = "nvidia-smi unavailable"
        return out

    line = q.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 6:
        out["collection_error"] = f"unexpected nvidia-smi csv: {line[:120]}"
        return out

    def num(v: str) -> Optional[float]:
        if v in ("", "[N/A]", "N/A", "[Not Supported]", "Not Supported"):
            return None
        try:
            return float(v)
        except ValueError:
            return None

    name = parts[0]
    driver = parts[1]
    count = int(float(parts[2])) if num(parts[2]) is not None else 1
    util = num(parts[3])
    mem_used = num(parts[4])
    mem_total = num(parts[5])
    temp = num(parts[6]) if len(parts) > 6 else None
    power = num(parts[7]) if len(parts) > 7 else None
    power_lim = num(parts[8]) if len(parts) > 8 else None
    fan = num(parts[9]) if len(parts) > 9 else None
    clk_core = num(parts[10]) if len(parts) > 10 else None
    clk_mem = num(parts[11]) if len(parts) > 11 else None

    vram_pct = None
    if mem_used is not None and mem_total and mem_total > 0:
        vram_pct = round(100.0 * mem_used / mem_total, 1)

    procs: List[Dict[str, Any]] = []
    proc_out = _run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    if proc_out:
        for pline in proc_out.strip().splitlines():
            pp = [x.strip() for x in pline.split(",")]
            if len(pp) >= 3:
                procs.append(
                    {
                        "pid": pp[0],
                        "name": pp[1],
                        "used_gpu_memory_mb": num(pp[2]),
                    }
                )

    out.update(
        {
            "gpu_available": True,
            "gpu_vendor": "NVIDIA",
            "gpu_model": name,
            "gpu_count": count,
            "gpu_driver": driver,
            "gpu_runtime": "CUDA/nvidia-smi",
            "gpu_util_percent": util,
            "gpu_vram_used_mb": mem_used,
            "gpu_vram_total_mb": mem_total,
            "gpu_vram_percent": vram_pct,
            "gpu_temp_c": temp,
            "gpu_power_w": power,
            "gpu_power_limit_w": power_lim,
            "gpu_fan_percent": fan,
            "gpu_core_clock_mhz": clk_core,
            "gpu_memory_clock_mhz": clk_mem,
            "gpu_processes": procs,
        }
    )
    return out


def collect_ollama_status(gpu: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ollama service + resident models + execution mode evidence."""
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    out: Dict[str, Any] = {
        "OLLAMA_SERVICE_ACTIVE": None,
        "OLLAMA_RESIDENT_MODELS": [],
        "OLLAMA_ACTIVE_MODEL": None,
        "OLLAMA_GPU_PROCESS_VISIBLE": False,
        "OLLAMA_GPU_MEMORY_MB": None,
        "OLLAMA_EXECUTION_MODE": "UNKNOWN",
        "error": None,
    }
    try:
        active = subprocess.check_output(
            ["systemctl", "is-active", "ollama"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        out["OLLAMA_SERVICE_ACTIVE"] = active == "active"
    except Exception:
        # process may still run without unit name
        out["OLLAMA_SERVICE_ACTIVE"] = None

    try:
        with urllib.request.urlopen(f"{base}/api/ps", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("models") or []
        names = []
        active = None
        max_vram = 0.0
        max_size = 0.0
        for m in models:
            name = m.get("name") or m.get("model")
            if name:
                names.append(name)
                active = name
            size = float(m.get("size") or 0)
            vram = float(m.get("size_vram") or 0)
            max_size = max(max_size, size)
            max_vram = max(max_vram, vram)
        out["OLLAMA_RESIDENT_MODELS"] = names
        out["OLLAMA_ACTIVE_MODEL"] = active
        if max_vram > 0:
            out["OLLAMA_GPU_MEMORY_MB"] = round(max_vram / (1024 * 1024), 1)
        # Execution mode from size_vram vs size
        if not names:
            out["OLLAMA_EXECUTION_MODE"] = "IDLE"
        elif max_size <= 0:
            out["OLLAMA_EXECUTION_MODE"] = "UNKNOWN"
        elif max_vram <= 0:
            out["OLLAMA_EXECUTION_MODE"] = "CPU"
        elif max_vram >= 0.85 * max_size:
            out["OLLAMA_EXECUTION_MODE"] = "GPU"
        else:
            out["OLLAMA_EXECUTION_MODE"] = "PARTIAL_GPU"
    except Exception as exc:
        out["error"] = str(exc)
        if out["OLLAMA_EXECUTION_MODE"] == "UNKNOWN" and not out["OLLAMA_RESIDENT_MODELS"]:
            out["OLLAMA_EXECUTION_MODE"] = "IDLE" if out.get("OLLAMA_SERVICE_ACTIVE") else "UNKNOWN"

    # Cross-check GPU process list for ollama/llama-server
    gpu = gpu or {}
    ollama_mb = 0.0
    visible = False
    for p in gpu.get("gpu_processes") or []:
        name = str(p.get("name") or "").lower()
        if "ollama" in name or "llama-server" in name:
            visible = True
            mb = p.get("used_gpu_memory_mb")
            if mb is not None:
                ollama_mb += float(mb)
    out["OLLAMA_GPU_PROCESS_VISIBLE"] = visible
    if visible and out.get("OLLAMA_GPU_MEMORY_MB") is None and ollama_mb > 0:
        out["OLLAMA_GPU_MEMORY_MB"] = round(ollama_mb, 1)
    return out


def collect_s13_gpu_bundle() -> Dict[str, Any]:
    gpu = collect_nvidia_gpu()
    ollama = collect_ollama_status(gpu)
    return {"gpu": gpu, "ollama": ollama}
