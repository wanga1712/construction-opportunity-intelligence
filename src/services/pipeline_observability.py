"""Pipeline / worker / intake observability for the CRM contour.

Read-only. Two sources of truth:

* the document-intelligence DB — queue depth and intake timestamps;
* the local host (S13) — systemd unit state, journal cycles, CPU/load and top
  processes.  Host probes are wrapped so the module degrades to "unknown" on
  any machine without systemd/journalctl (e.g. the Windows dev box).

Cost control: the compact line and the full page collect host facts with the
fewest possible subprocesses — one multi-unit ``systemctl is-active``, one
multi-unit ``journalctl`` and one ``ps``.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras

from src.services.doc_db_runtime import require_doc_db_connect_kwargs
from src.services.queue_first_service import PIPELINE_GENERATION

logger = logging.getLogger(__name__)

BAND_WORKERS = [
    ("tender-docs-band-gold-1", "Документы · GOLD 1"),
    ("tender-docs-band-gold-2", "Документы · GOLD 2"),
    ("tender-docs-band-silver", "Документы · SILVER"),
    ("tender-docs-band-bronze", "Документы · BRONZE"),
    ("tender-docs-band-wood", "Документы · WOOD+UNSCORED"),
]

CRM_SERVICES = [
    ("crm-v3-factual-feeder", "Feeder: admit закупок в очередь"),
    ("crm-v3-autonomous-worker", "Autonomous worker: разбор кандидатов"),
    ("crm-v3-context-validator", "Context validator: проверка документов"),
    ("crm-v3-learning-observer", "Learning observer"),
    ("crm-v3-shadow-predictor", "Shadow predictor"),
    ("crm-computer-tz-loop", "Computer TZ loop"),
]

SYNC_UNIT = "crm-procurement-sync"
FEEDER_UNIT = "crm-v3-factual-feeder"

TIMERS = [
    ("crm-procurement-sync.timer", "Синк закупок (каждые 15 мин)"),
    ("crm-v3-analytics-refresh.timer", "Аналитика V3 (час)"),
    ("crm-v3-daily-medal-reevaluation.timer", "Пересчёт медалей (12:00)"),
]

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})")


# ── Host probes (degrade to empty on non-systemd hosts) ─────────────────────

def _run(cmd: Sequence[str], timeout: float = 8.0) -> str:
    try:
        res = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout, check=False
        )
        return (res.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _systemctl_many(units: Sequence[str]) -> Dict[str, str]:
    """One ``systemctl is-active`` call for many units (order-preserving)."""
    if not units:
        return {}
    out = _run(["systemctl", "is-active", *units], timeout=8)
    if not out:
        return {u: "unknown" for u in units}
    lines = out.splitlines()
    return {u: (lines[i] if i < len(lines) else "unknown") for i, u in enumerate(units)}


JournalEntry = Tuple[str, Optional[datetime], str]


def _journal_multi(units: Sequence[str], lines: int = 200) -> List[JournalEntry]:
    """One ``journalctl -o json`` call for several units → [(unit, ts, msg), ...].

    JSON output is required: for application stdout systemd labels the line with
    the executable (``python[pid]``), not the unit, so short-iso cannot be
    attributed back to ``_SYSTEMD_UNIT``.
    """
    if not units:
        return []
    cmd = ["journalctl"]
    for u in units:
        cmd.extend(["-u", u])
    cmd.extend(["-n", str(lines), "--no-pager", "-o", "json"])
    raw = _run(cmd, timeout=12)
    entries: List[JournalEntry] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        msg = obj.get("MESSAGE")
        if not isinstance(msg, str):
            continue
        ts = None
        ts_us = obj.get("__REALTIME_TIMESTAMP")
        try:
            ts = datetime.fromtimestamp(int(ts_us) / 1_000_000)
        except (TypeError, ValueError):
            ts = None
        entries.append((str(obj.get("_SYSTEMD_UNIT") or ""), ts, msg))
    return entries


def _extract_dict(msg: str, marker: str) -> Optional[Dict[str, Any]]:
    if marker not in msg:
        return None
    start = msg.find("{", msg.find(marker))
    end = msg.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = ast.literal_eval(msg[start : end + 1])
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, dict) else None


def _cycles(
    entries: Sequence[JournalEntry], unit: str, marker: str, limit: int
) -> List[Dict[str, Any]]:
    cycles: List[Dict[str, Any]] = []
    for u, ts, msg in reversed(entries):
        if u and u != unit:
            continue
        payload = _extract_dict(msg, marker)
        if payload is None:
            continue
        cycles.append({"at": ts, **payload})
        if len(cycles) >= limit:
            break
    return cycles


def _proc_stat() -> Tuple[float, ...]:
    try:
        with open("/proc/stat", "r", encoding="utf-8") as fh:
            parts = fh.readline().split()[1:8]
        return tuple(float(x) for x in parts)
    except Exception:  # noqa: BLE001
        return ()


def _cpu_busy_pct(interval: float = 0.12) -> Optional[float]:
    a = _proc_stat()
    if not a:
        return None
    time.sleep(interval)
    b = _proc_stat()
    if not b:
        return None
    d = [y - x for x, y in zip(a, b)]
    total = sum(d)
    if total <= 0:
        return None
    idle = d[3] + (d[4] if len(d) > 4 else 0.0)
    return round(max(0.0, min(100.0, (total - idle) / total * 100.0)), 1)


def _ps_top(limit: int = 6) -> List[Dict[str, Any]]:
    """One ``ps`` call → top processes by CPU (name only, secret-safe)."""
    out = _run(
        ["ps", "-eo", "pcpu=,pmem=,rss=,comm=", "--sort=-pcpu", "--no-headers"],
        timeout=8,
    )
    procs = []
    for line in out.splitlines()[:limit]:
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            procs.append(
                {
                    "cpu_pct": float(parts[0].replace(",", ".")),
                    "mem_pct": float(parts[1].replace(",", ".")),
                    "ram_mb": round(int(parts[2]) / 1024, 1),
                    "name": parts[3].strip(),
                }
            )
        except ValueError:
            continue
    return procs


def _load1() -> Optional[float]:
    try:
        return round(os.getloadavg()[0], 2)
    except Exception:  # noqa: BLE001
        return None


# ── DB part ─────────────────────────────────────────────────────────────────

def _doc_conn():
    kwargs = require_doc_db_connect_kwargs()
    kwargs["connect_timeout"] = 5
    kwargs["options"] = "-c statement_timeout=15000"
    conn = psycopg2.connect(**kwargs)
    conn.autocommit = True
    return conn


def _queue_state() -> Dict[str, Any]:
    conn = _doc_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT status, count(*) AS n FROM document_processing_queue "
                "WHERE pipeline_generation = %s GROUP BY status",
                (PIPELINE_GENERATION,),
            )
            by_status = {r["status"]: int(r["n"]) for r in cur.fetchall()}
            cur.execute(
                "SELECT max(created_at) AS last_created, "
                "EXTRACT(EPOCH FROM (now() - max(created_at))) / 3600.0 AS hours_since, "
                "count(*) FILTER (WHERE created_at > now() - interval '24 hours') AS new_24h "
                "FROM document_processing_queue WHERE pipeline_generation = %s",
                (PIPELINE_GENERATION,),
            )
            intake = dict(cur.fetchone() or {})
            cur.execute(
                "SELECT to_char(date_trunc('hour', created_at), 'DD.MM HH24:00') AS h, "
                "count(*) AS n FROM document_processing_queue "
                "WHERE pipeline_generation = %s AND created_at > now() - interval '48 hours' "
                "GROUP BY 1 ORDER BY 1",
                (PIPELINE_GENERATION,),
            )
            intake["by_hour"] = [dict(r) for r in cur.fetchall()]
        return {"by_status": by_status, "intake": intake}
    except Exception as exc:  # noqa: BLE001
        logger.warning("pipeline queue state unavailable: %s", type(exc).__name__)
        return {"by_status": {}, "intake": {}}
    finally:
        conn.close()


# ── Assembly ────────────────────────────────────────────────────────────────

def _collect_host(*, light: bool) -> Dict[str, Any]:
    """Host facts. ``light`` skips the extra CPU sampling for the first screen."""
    units = [SYNC_UNIT, "ollama"]
    states = _systemctl_many(units)
    ps = _ps_top(limit=6)
    ollama_pct = None
    for p in ps:
        if "ollama" in p["name"] or "llama" in p["name"]:
            ollama_pct = p["cpu_pct"]
            break
    if light:
        # reuse the ps sample for a cheap "is the model busy" signal
        cpu_pct = round(sum(p["cpu_pct"] for p in ps), 1) if ps else None
    else:
        cpu_pct = _cpu_busy_pct()
    return {
        "cpu_pct": cpu_pct,
        "load_1": _load1(),
        "core_count": os.cpu_count(),
        "top_cpu": ps,
        "ollama_pct": ollama_pct,
        "ollama_active": states.get("ollama", "unknown"),
    }


def load_pipeline_status(cycle_limit: int = 8, *, light: bool = False) -> Dict[str, Any]:
    """Pipeline snapshot for the «Конвейер» page (``light`` for the first screen)."""
    queue = _queue_state()
    by_status = queue["by_status"]

    band_units = [u for u, _ in BAND_WORKERS]
    all_units = band_units + [u for u, _ in CRM_SERVICES] + [u for u, _ in TIMERS]
    states = _systemctl_many(all_units)
    entries = _journal_multi(band_units + [FEEDER_UNIT, SYNC_UNIT], lines=200)

    last_by_unit: Dict[str, Tuple[Optional[datetime], str]] = {}
    for unit, ts, msg in entries:
        if unit:
            last_by_unit[unit] = (ts, msg)

    workers = []
    for unit, label in BAND_WORKERS:
        active = states.get(unit, "unknown")
        ts, msg = last_by_unit.get(unit, (None, ""))
        idle = ("No tasks" in msg) or ("sleeping" in msg)
        workers.append(
            {
                "unit": unit, "label": label, "active": active,
                "busy": bool(active == "active" and msg and not idle),
                "last_log_at": ts, "last_message": msg[:200],
            }
        )

    return {
        "queue": {
            "by_status": by_status,
            "pending": by_status.get("PENDING", 0) + by_status.get("PRE_RESEARCH_WAITING", 0),
            "processing": by_status.get("PROCESSING", 0) + by_status.get("RUNNING", 0),
            "completed": by_status.get("COMPLETED", 0),
            "failed": by_status.get("FAILED", 0),
            "no_links": by_status.get("NO_LINKS", 0),
            "total": sum(by_status.values()),
        },
        "intake": queue["intake"],
        "workers": workers,
        "crm_services": [
            {"unit": u, "label": l, "active": states.get(u, "unknown")}
            for u, l in CRM_SERVICES
        ],
        "timers": [
            {"unit": u, "label": l, "active": states.get(u, "unknown")}
            for u, l in TIMERS
        ],
        "feeder": (_cycles(entries, FEEDER_UNIT, "factual feeder cycle:", 1) or [{}])[0],
        "feeder_cycles": _cycles(entries, FEEDER_UNIT, "factual feeder cycle:", cycle_limit),
        "sync": (_cycles(entries, SYNC_UNIT, "Sync result:", 1) or [{}])[0],
        "sync_runs": _cycles(entries, SYNC_UNIT, "Sync result:", cycle_limit),
        "host": _collect_host(light=light),
    }


def load_pipeline_line() -> Dict[str, Any]:
    """Compact one-line snapshot for the queue-first first screen."""
    try:
        status = load_pipeline_status(cycle_limit=2, light=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pipeline line unavailable: %s", type(exc).__name__)
        return {"ok": False, "reason": type(exc).__name__}

    intake = status.get("intake") or {}
    feeder = status.get("feeder") or {}
    sync = status.get("sync") or {}
    workers = status.get("workers") or []
    queue = status.get("queue") or {}
    host = status.get("host") or {}
    busy = sum(1 for w in workers if w.get("busy"))
    known = any(str(w.get("active")) not in ("unknown", "") for w in workers)
    return {
        "ok": True,
        "hours_since_intake": (
            round(float(intake["hours_since"]), 1)
            if intake.get("hours_since") is not None
            else None
        ),
        "new_24h": intake.get("new_24h"),
        "sync_open_44": sync.get("source_open_44"),
        "sync_open_223": sync.get("source_open_223"),
        "feeder_admitted": feeder.get("admitted_count"),
        "feeder_depth": feeder.get("queue_depth_after"),
        "workers_busy": busy if known else None,
        "workers_idle": (len(workers) - busy) if known else None,
        "queue_pending": queue.get("pending"),
        "queue_processing": queue.get("processing"),
        "cpu_pct": host.get("cpu_pct"),
        "ollama_pct": host.get("ollama_pct"),
    }
