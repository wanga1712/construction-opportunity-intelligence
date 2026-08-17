"""Readiness gates for V3 golden canary — fail closed, no model call on failure."""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.golden_canary_config import (
    FROZEN_AI_UNITS,
    FROZEN_DOC_UNITS,
    PRODUCTION_PROJECTION_WRITER_REQUIRED,
    READINESS_INITIAL_DELAY_SEC,
    READINESS_MAX_WAIT_SEC,
    READINESS_RETRY_INTERVAL_SEC,
)
from src.services.commercial_routing_v3.projection_writer import (
    LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH,
    PRODUCTION_PROJECTION_WRITER,
)
from src.services.commercial_routing_v3.schema_readiness import check_v3_schema_readiness


@dataclass
class ReadinessResult:
    ok: bool
    checks: Dict[str, Any] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    waited_sec: float = 0.0
    initial_delay_sec: int = READINESS_INITIAL_DELAY_SEC
    max_wait_sec: int = READINESS_MAX_WAIT_SEC

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": self.checks,
            "failures": self.failures,
            "waited_sec": self.waited_sec,
            "initial_delay_sec": self.initial_delay_sec,
            "max_wait_sec": self.max_wait_sec,
        }


def _systemctl_is_active(unit: str) -> str:
    try:
        p = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (p.stdout or "").strip() or "unknown"
    except Exception as exc:
        return f"error:{type(exc).__name__}"


def _ollama_reachable(timeout: float = 5.0) -> Dict[str, Any]:
    url = "http://127.0.0.1:11434/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name") for m in (data.get("models") or []) if isinstance(m, dict)]
        has_qwen = any(isinstance(n, str) and n.startswith("qwen2.5") for n in models)
        return {"ok": True, "models": models[:20], "has_qwen2_5": has_qwen}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}


def evaluate_readiness(
    *,
    crm_db,
    tender_db,
    skip_sleep: bool = False,
    sleep_fn=time.sleep,
) -> ReadinessResult:
    """Bounded readiness: optional initial delay + retries up to max wait."""
    result = ReadinessResult(ok=False)
    t0 = time.monotonic()

    if not skip_sleep and READINESS_INITIAL_DELAY_SEC > 0:
        sleep_fn(READINESS_INITIAL_DELAY_SEC)

    deadline = t0 + READINESS_MAX_WAIT_SEC
    last: Optional[ReadinessResult] = None

    while True:
        last = _once(crm_db=crm_db, tender_db=tender_db)
        last.waited_sec = time.monotonic() - t0
        if last.ok:
            return last
        if time.monotonic() >= deadline:
            last.failures.append("READINESS_TIMEOUT")
            last.ok = False
            return last
        sleep_fn(READINESS_RETRY_INTERVAL_SEC)


def _once(*, crm_db, tender_db) -> ReadinessResult:
    r = ReadinessResult(ok=True)
    checks = r.checks

    # Projection writer canonical
    checks["PRODUCTION_PROJECTION_WRITER"] = PRODUCTION_PROJECTION_WRITER
    if PRODUCTION_PROJECTION_WRITER != PRODUCTION_PROJECTION_WRITER_REQUIRED:
        r.failures.append("PROJECTION_WRITER_NOT_V3")
    if LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH:
        r.failures.append("LEGACY_PRODUCTION_WRITER_ENABLED")

    # Local CRM
    try:
        row = crm_db.execute_query(
            "SELECT current_database() AS db, inet_server_addr()::text AS addr, current_user AS usr"
        )[0]
        checks["crm_session"] = dict(row) if hasattr(row, "keys") else row
        db = row["db"] if isinstance(row, dict) else row[0]
        addr = str(row["addr"] if isinstance(row, dict) else row[1] or "")
        if db != "crm":
            r.failures.append("CRM_DB_NAME")
        if "127.0.0.1" not in addr and "None" not in addr and addr not in ("", "None"):
            # unix socket shows None — acceptable for local
            if not addr.startswith("127."):
                r.failures.append(f"CRM_NOT_LOCAL:{addr}")
        n = crm_db.execute_query("SELECT count(*) AS c FROM crm_procurements")[0]
        checks["crm_procurements"] = n["c"] if isinstance(n, dict) else n[0]
    except Exception as exc:
        r.failures.append(f"CRM_UNREACHABLE:{type(exc).__name__}")

    # S7 RO
    try:
        n44 = tender_db.execute_query("SELECT count(*) FROM reestr_contract_44_fz")[0]
        checks["tm_44"] = n44[0] if not isinstance(n44, dict) else list(n44.values())[0]
        try:
            tender_db.execute_update("CREATE TEMP TABLE __canary_ro_probe(x int)")
            r.failures.append("S7_WRITE_UNEXPECTED")
            checks["SOURCE_DB_READ_ONLY"] = False
        except Exception as exc:
            checks["SOURCE_DB_READ_ONLY"] = True
            checks["SOURCE_DB_READ_ONLY_exc"] = type(exc).__name__
    except Exception as exc:
        r.failures.append(f"S7_UNREACHABLE:{type(exc).__name__}")

    # V3 schema + registry
    try:
        sch = check_v3_schema_readiness(crm_db)
        checks["v3_schema_ready"] = sch.ready
        checks["v3_schema_missing"] = list(sch.missing)[:20]
        if not sch.ready:
            r.failures.append("V3_SCHEMA_NOT_READY")
        reg = crm_db.execute_query(
            """
            SELECT count(*) AS c FROM crm_product_categories
            WHERE coalesce(is_active,true)=true
            """
        )[0]
        checks["registry_active_categories"] = reg["c"] if isinstance(reg, dict) else reg[0]
        try:
            from src.services.commercial_taxonomy_registry import load_active_commercial_categories

            cats = load_active_commercial_categories(crm_db, allow_legacy_fallback=False)
            checks["registry_hash_proxy"] = f"active_cats={len(cats)}"
            checks["registry_version"] = "live"
        except Exception as exc:
            r.failures.append(f"REGISTRY_UNREADABLE:{type(exc).__name__}")
    except Exception as exc:
        r.failures.append(f"SCHEMA_CHECK:{type(exc).__name__}")

    # Sync timer healthy
    sync_timer = _systemctl_is_active("crm-procurement-sync.timer")
    checks["crm-procurement-sync.timer"] = sync_timer
    if sync_timer != "active":
        r.failures.append("SYNC_TIMER_NOT_ACTIVE")

    # Ollama / Qwen
    oll = _ollama_reachable()
    checks["ollama"] = oll
    if not oll.get("ok"):
        r.failures.append("OLLAMA_UNREACHABLE")
    elif not oll.get("has_qwen2_5"):
        r.failures.append("QWEN_MODEL_MISSING")

    # AI + docs frozen
    for u in FROZEN_AI_UNITS:
        st = _systemctl_is_active(u)
        checks[u] = st
        if st == "active":
            r.failures.append(f"AI_NOT_FROZEN:{u}")
    for u in FROZEN_DOC_UNITS:
        st = _systemctl_is_active(u)
        checks[u] = st
        if st == "active":
            r.failures.append(f"DOCS_NOT_FROZEN:{u}")

    checks["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    r.ok = len(r.failures) == 0
    return r
