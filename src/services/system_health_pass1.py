"""Read-only PASS1 progress + taxonomy coverage telemetry (collector-side).

This module is invoked ONLY by the system-health collector (never by the UI).
It produces a compact snapshot block the Streamlit System Health page renders
without touching the database. All queries are bounded read-only SELECTs.

Definitions (per SYSTEM-HEALTH-PASS1-PROGRESS-PANEL-1):
  PASS1_DONE      - terminal PASS1 outcome: classified/scored, completed-no-medal,
                    NEEDS_REVIEW, or terminal FAILED (attempts >= max).
  PASS1_RUNNING   - ai_assessment_status = RUNNING (in-flight).
  PASS1_REMAINING - the drain's own TOTAL_ROUTING_ELIGIBLE_BACKLOG
                    (ACTIVE + AWARDED lanes from routing_status.json).
Nothing here changes routing/drain/classifier/taxonomy.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROUTING_STATUS_PATH = Path(
    os.environ.get(
        "CRM_V3_ROUTING_STATUS_PATH",
        "/var/lib/crm-v3-canary/continuous_backlog_drain/routing_status.json",
    )
)
PROJECT_ENV_PATH = Path("/opt/CRM_Streamlit/.env")


def _backlog_cache_path() -> Path:
    root = os.environ.get("CRM_SYSTEM_HEALTH_DIR", "/var/lib/crm-system-health")
    return Path(root) / "pass1_backlog_cache.json"

ADMISSION_POLICY = "BUSINESS_RESEARCH_ADMISSION_V2"
TERMINAL_STATUSES = ("COMPLETED", "NEEDS_REVIEW", "FAILED")
ACTIVE_STATUSES = ("COMPLETED", "NEEDS_REVIEW", "FAILED", "RUNNING")
DRAIN_UNIT = "crm-ai-assessment-runner.service"

SUSPEND_HOUR = int(os.environ.get("CRM_S13_SUSPEND_HOUR", "23"))
WAKE_HOUR = int(os.environ.get("CRM_S13_WAKE_HOUR", "6"))
STALL_AFTER_SEC = 30 * 60
MAX_ROUTING_ATTEMPTS = int(os.environ.get("CRM_V3_ROUTING_MAX_ATTEMPTS", "3"))

REQUIRED_CATEGORIES = (
    "computers",
    "lighting",
    "waterproofing",
    "flooring",
    "drainage_water_management",
)
CATEGORY_TOP_N = 12

_env_loaded = False
_conn = None  # cached psycopg2 connection (collector process only)


def _ensure_env() -> None:
    """Load /opt/CRM_Streamlit/.env without clobbering existing environment."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    try:
        if PROJECT_ENV_PATH.is_file():
            for line in PROJECT_ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key and key not in os.environ:
                    os.environ[key] = value.strip().strip('"').strip("'")
    except Exception:
        pass


def _get_conn():
    global _conn
    if _conn is not None:
        return _conn
    _ensure_env()
    import psycopg2

    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kwargs = dict(require_crm_db_connect_kwargs())
    kwargs["connect_timeout"] = 5
    _conn = psycopg2.connect(**kwargs)
    _conn.autocommit = True
    return _conn


def _query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    global _conn
    import psycopg2
    from psycopg2.extras import RealDictCursor

    for attempt in (0, 1):
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in (cur.fetchall() or [])]
        except Exception:
            try:
                if _conn is not None:
                    _conn.close()
            except Exception:
                pass
            _conn = None
            if attempt == 1:
                raise
    return []


def _read_routing_status() -> Dict[str, Any]:
    try:
        return json.loads(ROUTING_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_remaining(rs: Dict[str, Any]) -> Dict[str, Any]:
    """Backlog from routing_status.json; keep last known when a max_runtime
    finish omits the backlog keys (the drain's own final payload has no counts)."""
    cache_path = _backlog_cache_path()
    if "TOTAL_ELIGIBLE_BACKLOG" in rs:
        old = {}
        try:
            old = json.loads(cache_path.read_text(encoding="utf-8")) or {}
        except Exception:
            old = {}
        value = {
            "TOTAL_ELIGIBLE_BACKLOG": int(rs.get("TOTAL_ELIGIBLE_BACKLOG") or 0),
            "ACTIVE_BACKLOG": int(rs.get("ACTIVE_BACKLOG") or 0),
            "AWARDED_BACKLOG": int(rs.get("AWARDED_BACKLOG") or 0),
            "source_updated_at": rs.get("updated_at"),
            "LAST_COMPLETED_AT": rs.get("LAST_COMPLETED_AT") or old.get("LAST_COMPLETED_AT"),
            "CURRENT_PROCUREMENT_ID": rs.get("CURRENT_PROCUREMENT_ID"),
        }
        value["ACTIVE_BACKLOG"] = int((rs.get("backlog") or {}).get("ACTIVE_BACKLOG", value["ACTIVE_BACKLOG"]) or 0)
        value["AWARDED_BACKLOG"] = int((rs.get("backlog") or {}).get("AWARDED_BACKLOG", value["AWARDED_BACKLOG"]) or 0)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return value
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, dict):
            return cached
    except Exception:
        pass
    return {"TOTAL_ELIGIBLE_BACKLOG": 0, "ACTIVE_BACKLOG": 0, "AWARDED_BACKLOG": 0, "source_updated_at": None}


def _count_writers() -> int:
    try:
        out = subprocess.run(
            ["pgrep", "-fc", "crm_ai_assessment_runner.py"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return int(out or "0")
    except Exception:
        return 0


def _journal_rate(pattern: str, minutes: int = 60) -> Optional[int]:
    try:
        proc = subprocess.run(
            ["journalctl", "-u", DRAIN_UNIT, "--since", f"-{minutes} min", "--no-pager"],
            capture_output=True, text=True, timeout=20,
        )
        if proc.returncode != 0:
            return None
        return sum(1 for line in proc.stdout.splitlines() if pattern in line)
    except Exception:
        return None


def _add_work_hours(work_hours: float, now: datetime) -> Optional[datetime]:
    """Add working hours skipping the nightly 23:00-06:00 suspend window."""
    if work_hours is None or work_hours < 0:
        return None
    remaining = work_hours
    cur = now
    guard = 0
    while remaining > 0 and guard < 400:
        guard += 1
        if cur.hour >= SUSPEND_HOUR or cur.hour < WAKE_HOUR:
            nxt = cur.replace(hour=WAKE_HOUR, minute=0, second=0, microsecond=0)
            if cur.hour >= SUSPEND_HOUR:
                nxt = nxt + timedelta(days=1)
            cur = nxt
            continue
        window_end = cur.replace(hour=SUSPEND_HOUR, minute=0, second=0, microsecond=0)
        available = (window_end - cur).total_seconds() / 3600.0
        if available >= remaining:
            return cur + timedelta(hours=remaining)
        remaining -= available
        cur = window_end
    return cur


def collect_pass1_telemetry(*, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    out: Dict[str, Any] = {
        "available": False,
        "collected_at": now.isoformat(),
        "error": None,
    }
    try:
        rows = _query(
            """
            SELECT a.source_lifecycle AS lc,
                   cp.ai_assessment_status AS st,
                   CASE WHEN o.procurement_id IS NULL THEN false ELSE true END AS has_opp,
                   count(DISTINCT cp.id) AS n,
                   count(*) FILTER (
                     WHERE cp.ai_assessment_status = 'FAILED'
                       AND coalesce(cp.ai_routing_attempt_count,0) >= %s
                   ) AS n_maxed
            FROM crm_procurements cp
            JOIN crm_procurement_scope_authority a ON a.procurement_id = cp.id
            LEFT JOIN crm_procurement_category_opportunities o
                   ON o.procurement_id = cp.id AND o.status = 'CURRENT'
            WHERE a.admission_state = 'ELIGIBLE'
              AND a.admission_policy_version = %s
              AND cp.ai_assessment_status = ANY(%s)
            GROUP BY 1, 2, 3
            """,
            (MAX_ROUTING_ATTEMPTS, ADMISSION_POLICY, list(ACTIVE_STATUSES)),
        )
        done = running = 0
        classified = no_entry = needs_review = failed_terminal = 0
        open_done = awarded_done = 0
        for r in rows:
            lc = (r.get("lc") or "").upper()
            st = (r.get("st") or "").upper()
            n = int(r.get("n") or 0)
            if st == "RUNNING":
                running += n
                continue
            if st == "COMPLETED":
                done += n
                if r.get("has_opp"):
                    classified += n
                else:
                    no_entry += n
            elif st == "NEEDS_REVIEW":
                done += n
                needs_review += n
            elif st == "FAILED":
                maxed = int(r.get("n_maxed") or 0)
                done += maxed
                failed_terminal += maxed
            if lc == "OPEN":
                open_done += n if st != "FAILED" else int(r.get("n_maxed") or 0)
            elif lc == "AWARDED":
                awarded_done += n if st != "FAILED" else int(r.get("n_maxed") or 0)

        rs = _read_routing_status()
        rb = _resolve_remaining(rs)
        remaining = int(rb.get("TOTAL_ELIGIBLE_BACKLOG") or 0)
        remaining_open = int(rb.get("ACTIVE_BACKLOG") or 0)
        remaining_awarded = int(rb.get("AWARDED_BACKLOG") or 0)
        if not remaining and (remaining_open or remaining_awarded):
            remaining = remaining_open + remaining_awarded

        thr = _query(
            """
            SELECT
              count(*) FILTER (WHERE ai_assessed_at >= now() - interval '15 minutes') AS last15,
              count(*) FILTER (WHERE ai_assessed_at >= now() - interval '60 minutes') AS last60,
              EXTRACT(EPOCH FROM (now() - max(ai_assessed_at))) AS last_age
            FROM crm_procurements
            WHERE ai_assessment_status IN ('COMPLETED', 'NEEDS_REVIEW')
            """
        )
        last15 = int((thr[0].get("last15") if thr else 0) or 0)
        last60 = int((thr[0].get("last60") if thr else 0) or 0)
        last_age = thr[0].get("last_age") if thr else None

        cats = _query(
            """
            SELECT commercial_category_code AS category,
                   count(*) AS total,
                   count(*) FILTER (WHERE commercial_subcategory_code IS NOT NULL) AS resolved,
                   count(*) FILTER (WHERE commercial_subcategory_code IS NULL) AS unclassified
            FROM crm_procurement_category_opportunities
            WHERE status = 'CURRENT'
            GROUP BY 1
            ORDER BY total DESC
            """
        )
        categories = []
        for c in cats:
            total = int(c.get("total") or 0)
            resolved = int(c.get("resolved") or 0)
            categories.append({
                "category": c.get("category"),
                "total": total,
                "resolved": resolved,
                "unclassified": int(c.get("unclassified") or 0),
                "coverage_pct": round(100.0 * resolved / total, 1) if total else 0.0,
            })
        present = {c["category"] for c in categories}
        for req in REQUIRED_CATEGORIES:
            if req not in present:
                categories.append({
                    "category": req, "total": 0, "resolved": 0,
                    "unclassified": 0, "coverage_pct": 0.0,
                })

        workset = done + running + remaining
        progress = round(100.0 * done / workset, 1) if workset else 0.0
        rate = float(last60)
        eta_hours = round(remaining / rate, 1) if rate > 0 and remaining > 0 else None
        finish = _add_work_hours(eta_hours, now.astimezone(timezone(timedelta(hours=3)))) if eta_hours else None

        writers = _count_writers()
        mode = str(rs.get("ROUTING_MODE") or "").upper()
        if remaining <= 0 and writers == 0:
            state = "DONE"
        elif writers == 0:
            state = "PAUSED"
        elif last_age is not None and float(last_age) > STALL_AFTER_SEC:
            state = "STALLED"
        else:
            state = "RUNNING"

        out.update({
            "available": True,
            "mode": mode or None,
            "writers": writers,
            "state": state,
            "done": done,
            "running": running,
            "remaining": remaining,
            "remaining_open": remaining_open,
            "remaining_awarded": remaining_awarded,
            "workset": workset,
            "progress_pct": progress,
            "classified": classified,
            "no_commercial_entry": no_entry,
            "needs_review": needs_review,
            "failed_terminal": failed_terminal,
            "open_done": open_done,
            "open_remaining": remaining_open,
            "awarded_done": awarded_done,
            "awarded_remaining": remaining_awarded,
            "done_last_15m": last15,
            "done_last_60m": last60,
            "rate_per_hour": rate,
            "eta_work_hours": eta_hours,
            "estimated_finish": finish.isoformat() if finish else None,
            "current_procurement_id": rs.get("CURRENT_PROCUREMENT_ID") or rb.get("CURRENT_PROCUREMENT_ID"),
            "last_completed_at": rs.get("LAST_COMPLETED_AT") or rb.get("LAST_COMPLETED_AT"),
            "last_activity_age_sec": round(float(last_age), 1) if last_age is not None else None,
            "qwen_rate_last_60m": _journal_rate("V3 Ollama model"),
            "deterministic_rate_last_60m": _journal_rate("INITIAL_DETERMINISTIC_DONE"),
            "categories": categories,
        })
        return out
    except Exception as exc:  # never break the collector
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
