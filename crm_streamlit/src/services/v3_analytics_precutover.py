"""Pre-cutover Level-A analytics cache on S13 local disk (temporary).

Canonical future cache = S13 CRM crm_v3_analytics_*.
This file store is FALLBACK only and requires no CRM writes.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.services.v3_analytics_cache import (
    GenerationMeta,
    InMemoryAnalyticsCache,
    PostgresAnalyticsCache,
    SnapshotRow,
    cache_schema_ready,
)

PRECUTOVER_ANALYTICS_S7_WRITES = 0
PRECUTOVER_ANALYTICS_CRM_WRITES = 0
PRECUTOVER_CACHE_REMOVAL_REQUIRES_UI_REWRITE = False
CANONICAL_CACHE_PRIORITY = "S13_CRM"
PRECUTOVER_CACHE_PRIORITY = "FALLBACK"

DEFAULT_PRECUTOVER_DIR = "/var/lib/crm-v3-analytics-precutover"
LOCK_NAME = "refresh.lock"
META_NAME = "meta.json"
SNAP_NAME = "current_complete.json"


def precutover_dir() -> Path:
    return Path(os.environ.get("CRM_V3_ANALYTICS_PRECUTOVER_DIR", DEFAULT_PRECUTOVER_DIR))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class PreCutoverFileCache:
    """File-backed CacheStore for Level-A snapshots. schema_ready=True always."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else precutover_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.s7_writes = 0
        self.crm_writes = 0
        self._building_rows: Dict[int, List[SnapshotRow]] = {}
        self._building_meta: Dict[int, GenerationMeta] = {}

    def schema_ready(self) -> bool:
        return True

    def _meta_path(self) -> Path:
        return self.root / META_NAME

    def _snap_path(self) -> Path:
        return self.root / SNAP_NAME

    def _load_meta(self) -> Dict[str, Any]:
        p = self._meta_path()
        if not p.is_file():
            return {"next_id": 1, "current_id": None, "latest_id": None, "generations": {}}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"next_id": 1, "current_id": None, "latest_id": None, "generations": {}}

    def _save_meta(self, meta: Dict[str, Any]) -> None:
        _atomic_write_json(self._meta_path(), meta)

    def start_generation(self, trigger: str = "manual") -> GenerationMeta:
        meta = self._load_meta()
        gid = int(meta.get("next_id") or 1)
        meta["next_id"] = gid + 1
        gen = GenerationMeta(
            generation_id=gid,
            status="BUILDING",
            is_current=False,
            refresh_trigger=trigger,
            started_at=_utcnow(),
        )
        gens = meta.setdefault("generations", {})
        gens[str(gid)] = {
            "status": "BUILDING",
            "is_current": False,
            "refresh_trigger": trigger,
            "started_at": gen.started_at.isoformat(),
        }
        meta["latest_id"] = gid
        self._save_meta(meta)
        self._building_rows[gid] = []
        self._building_meta[gid] = gen
        return gen

    def write_rows(self, generation_id: int, rows: Sequence[SnapshotRow]) -> int:
        self._building_rows.setdefault(generation_id, []).extend(rows)
        # No CRM/S7 writes
        return len(rows)

    def complete_generation(
        self,
        generation_id: int,
        *,
        duration_ms: int,
        source_query_ms: int,
        crm_query_ms: int,
        cache_write_ms: int,
        routing_version: str = "",
        registry_version: str = "",
        registry_hash: str = "",
        metrics_collected: int = 0,
    ) -> GenerationMeta:
        rows = self._building_rows.get(generation_id, [])
        dashboard = None
        for r in rows:
            if r.metric_group == "DASHBOARD" and r.metric_name == "snapshot":
                dashboard = r.payload_json
                break
        finished = _utcnow()
        payload = {
            "generation_id": generation_id,
            "status": "COMPLETE",
            "finished_at": finished.isoformat(),
            "duration_ms": duration_ms,
            "source_query_ms": source_query_ms,
            "crm_query_ms": crm_query_ms,
            "cache_write_ms": cache_write_ms,
            "routing_version": routing_version,
            "registry_version": registry_version,
            "registry_hash": registry_hash,
            "metrics_collected": metrics_collected,
            "cache_kind": "PRECUTOVER_LEVEL_A",
            "dashboard": dashboard or {},
            "rows": [
                {
                    "snapshot_key": r.snapshot_key,
                    "metric_group": r.metric_group,
                    "metric_name": r.metric_name,
                    "metric_value": r.metric_value,
                    "payload_json": r.payload_json,
                    "source_contour": r.source_contour,
                }
                for r in rows
            ],
        }
        _atomic_write_json(self._snap_path(), payload)

        meta = self._load_meta()
        for g in meta.get("generations", {}).values():
            g["is_current"] = False
        meta.setdefault("generations", {})[str(generation_id)] = {
            "status": "COMPLETE",
            "is_current": True,
            "refresh_trigger": self._building_meta.get(generation_id, GenerationMeta(0, "", False, "")).refresh_trigger
            if generation_id in self._building_meta
            else "manual",
            "started_at": (
                self._building_meta[generation_id].started_at.isoformat()
                if generation_id in self._building_meta and self._building_meta[generation_id].started_at
                else None
            ),
            "finished_at": finished.isoformat(),
            "duration_ms": duration_ms,
            "source_query_ms": source_query_ms,
            "crm_query_ms": crm_query_ms,
            "cache_write_ms": cache_write_ms,
            "metrics_collected": metrics_collected,
        }
        meta["current_id"] = generation_id
        meta["latest_id"] = generation_id
        self._save_meta(meta)
        self._building_rows.pop(generation_id, None)
        return GenerationMeta(
            generation_id=generation_id,
            status="COMPLETE",
            is_current=True,
            refresh_trigger="manual",
            finished_at=finished,
            duration_ms=duration_ms,
            source_query_ms=source_query_ms,
            crm_query_ms=crm_query_ms,
            cache_write_ms=cache_write_ms,
            metrics_collected=metrics_collected,
        )

    def fail_generation(self, generation_id: int, error: str, *, duration_ms: int = 0) -> GenerationMeta:
        meta = self._load_meta()
        gens = meta.setdefault("generations", {})
        entry = gens.get(str(generation_id), {})
        entry.update(
            {
                "status": "FAILED",
                "is_current": False,
                "finished_at": _utcnow().isoformat(),
                "duration_ms": duration_ms,
                "error_summary": (error or "")[:2000],
            }
        )
        gens[str(generation_id)] = entry
        meta["latest_id"] = generation_id
        self._save_meta(meta)
        self._building_rows.pop(generation_id, None)
        return GenerationMeta(
            generation_id=generation_id,
            status="FAILED",
            is_current=False,
            refresh_trigger="manual",
            duration_ms=duration_ms,
            error_summary=(error or "")[:2000],
        )

    def get_current_complete(self) -> Optional[GenerationMeta]:
        meta = self._load_meta()
        cid = meta.get("current_id")
        if cid is None:
            return None
        g = meta.get("generations", {}).get(str(cid), {})
        if g.get("status") != "COMPLETE":
            return None
        finished = g.get("finished_at")
        return GenerationMeta(
            generation_id=int(cid),
            status="COMPLETE",
            is_current=True,
            refresh_trigger=str(g.get("refresh_trigger") or "manual"),
            finished_at=datetime.fromisoformat(finished) if finished else None,
            duration_ms=g.get("duration_ms"),
            source_query_ms=g.get("source_query_ms"),
            crm_query_ms=g.get("crm_query_ms"),
            cache_write_ms=g.get("cache_write_ms"),
            metrics_collected=int(g.get("metrics_collected") or 0),
        )

    def get_latest_attempt(self) -> Optional[GenerationMeta]:
        meta = self._load_meta()
        lid = meta.get("latest_id")
        if lid is None:
            return None
        g = meta.get("generations", {}).get(str(lid), {})
        finished = g.get("finished_at")
        return GenerationMeta(
            generation_id=int(lid),
            status=str(g.get("status") or "BUILDING"),
            is_current=bool(g.get("is_current")),
            refresh_trigger=str(g.get("refresh_trigger") or "manual"),
            finished_at=datetime.fromisoformat(finished) if finished else None,
            duration_ms=g.get("duration_ms"),
            error_summary=g.get("error_summary"),
        )

    def load_dashboard_payload(self, generation_id: int) -> Optional[Dict[str, Any]]:
        p = self._snap_path()
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        if int(data.get("generation_id") or -1) != int(generation_id):
            # stale file vs meta — still prefer file if current
            pass
        return dict(data.get("dashboard") or {})


def make_file_lock_pair(root: Path):
    lock_path = root / LOCK_NAME
    root.mkdir(parents=True, exist_ok=True)
    state: Dict[str, Any] = {"fh": None}

    def lock_try() -> bool:
        try:
            fh = open(lock_path, "a+", encoding="utf-8")
            try:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fh.close()
                return False
            except ImportError:
                # Windows fallback: exclusive create sentinel
                if state["fh"] is not None:
                    fh.close()
                    return False
            state["fh"] = fh
            return True
        except Exception:
            return False

    def lock_release() -> None:
        fh = state.get("fh")
        if fh is None:
            return
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass
        state["fh"] = None

    return lock_try, lock_release


def resolve_analytics_store(crm_db=None, *, force_precutover: bool = False):
    """Canonical CRM cache wins; otherwise pre-cutover file fallback."""
    if not force_precutover and crm_db is not None and cache_schema_ready(crm_db):
        return PostgresAnalyticsCache(crm_db), "CANONICAL_S13_CRM"
    return PreCutoverFileCache(), "PRECUTOVER_FILE"


def load_prepared_configuration(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """Read prepared (not deployed) taxonomy/OKPD stats from canonical report."""
    root = project_root or Path(__file__).resolve().parents[2]
    report = root / "data" / "legacy_okpd_migration_report.json"
    out: Dict[str, Any] = {
        "label": "PREPARED / NOT YET DEPLOYED TO V3 DB",
        "commercial_taxonomy": "prepared",
        "okpd_priors_prepared": None,
        "categories_with_priors": None,
        "categories_without_priors": [],
        "legacy_soft_negatives": None,
        "category_coverage": [],
        "source": str(report) if report.is_file() else None,
    }
    if not report.is_file():
        return out
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except Exception:
        return out
    coverage = list(data.get("category_coverage") or [])
    with_priors = [c for c in coverage if int(c.get("total_okpd_priors") or 0) > 0]
    without = [c.get("category_code") for c in coverage if int(c.get("total_okpd_priors") or 0) == 0]
    out.update(
        {
            "okpd_priors_prepared": data.get("GLOBAL_CATEGORY_OKPD_PRIORS_PREPARED"),
            "categories_with_priors": len(with_priors),
            "categories_without_priors": without,
            "legacy_soft_negatives": data.get("STOP_AS_NEGATIVE_SIGNAL")
            or data.get("LEGACY_STOP_RULES_TOTAL"),
            "category_coverage": coverage,
            "multi_category_okpd_count": data.get("MULTI_CATEGORY_OKPD_COUNT"),
        }
    )
    return out
