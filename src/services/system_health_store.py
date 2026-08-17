"""Atomic multi-host snapshot + bounded host-aware history."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services.system_health_config import (
    HEALTH_HISTORY_BOUNDED,
    HEALTH_HISTORY_MULTI_HOST,
    HISTORY_RETENTION_HOURS,
    history_db_path,
    latest_path,
)

PARTIAL_SNAPSHOT_VISIBLE = False
LAST_GOOD_SURVIVES_FAILURE = True
assert HEALTH_HISTORY_MULTI_HOST is True


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    assert PARTIAL_SNAPSHOT_VISIBLE is False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_health_", dir=str(path.parent))
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


def read_latest(root: Path | None = None) -> Optional[Dict[str, Any]]:
    path = latest_path(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_latest_safe(payload: Dict[str, Any], root: Path | None = None) -> None:
    atomic_write_json(latest_path(root), payload)


def ensure_history_db(root: Path | None = None) -> Path:
    assert HEALTH_HISTORY_BOUNDED is True
    db = history_db_path(root)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id TEXT NOT NULL,
                ts REAL NOT NULL,
                metric TEXT NOT NULL,
                value REAL,
                UNIQUE(host_id, ts, metric)
            )
            """
        )
        con.commit()
    finally:
        con.close()
    return db


def append_history_metrics(host_id: str, ts: float, metrics: Dict[str, Optional[float]], root: Path | None = None) -> None:
    db = ensure_history_db(root)
    con = sqlite3.connect(str(db))
    try:
        for metric, value in metrics.items():
            if value is None:
                continue
            con.execute(
                """
                INSERT OR REPLACE INTO metric_samples (host_id, ts, metric, value)
                VALUES (?, ?, ?, ?)
                """,
                (host_id, float(ts), metric, float(value)),
            )
        cutoff = time.time() - HISTORY_RETENTION_HOURS * 3600
        con.execute("DELETE FROM metric_samples WHERE ts < ?", (cutoff,))
        con.commit()
    finally:
        con.close()


def read_history(hours: float = 24.0, host_id: Optional[str] = None, root: Path | None = None) -> List[Dict[str, Any]]:
    db = history_db_path(root)
    if not db.is_file():
        return []
    con = sqlite3.connect(str(db))
    try:
        cutoff = time.time() - hours * 3600
        if host_id:
            rows = con.execute(
                """
                SELECT host_id, ts, metric, value FROM metric_samples
                WHERE ts >= ? AND host_id = ? ORDER BY ts
                """,
                (cutoff, host_id),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT host_id, ts, metric, value FROM metric_samples
                WHERE ts >= ? ORDER BY ts
                """,
                (cutoff,),
            ).fetchall()
        return [
            {"host_id": r[0], "ts": r[1], "metric": r[2], "value": r[3]}
            for r in rows
        ]
    finally:
        con.close()


def snapshot_status(collected_at_iso: Optional[str], *, stale_after: float, down_after: float, now: Optional[datetime] = None) -> str:
    if not collected_at_iso:
        return "COLLECTOR_DOWN"
    try:
        ts = datetime.fromisoformat(collected_at_iso)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        return "COLLECTOR_DOWN"
    age = ((now or _utcnow()) - ts).total_seconds()
    if age > down_after:
        return "COLLECTOR_DOWN"
    if age > stale_after:
        return "STALE"
    return "CURRENT"
