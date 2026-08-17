"""Persisted V3 analytics cache repository — CRM-owned, no runtime DDL."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

ANALYTICS_RUNTIME_DDL = False
FULL_PROCUREMENT_ROWS_CACHED_IN_ANALYTICS = False
ANALYTICS_CACHE_OWNER = "S13_CRM_DB"
STREAMLIT_MEMORY_CACHE_IS_CANONICAL = False

METRIC_GROUPS = (
    "SOURCE_FUNNEL",
    "PROJECTION_FUNNEL",
    "OKPD",
    "OKPD_FUNNEL",
    "TITLE_SIGNALS",
    "PROCUREMENT_FORMS",
    "CATEGORY_TRACKS",
    "SUBCATEGORIES",
    "CANDIDATE_MEDALS",
    "LIFECYCLE",
    "DISCOVERY",
    "QUALITY_FAILURES",
    "VERSIONS",
    "CATEGORY_COVERAGE",
    "MULTI_CATEGORY",
    "CONFIRMED_MEDALS",
    "DASHBOARD",
)

ANALYTICS_CACHE_DIMENSIONS = (
    "source_contour",
    "okpd_code",
    "okpd_prefix",
    "category_code",
    "subcategory_code",
    "opportunity_track",
    "candidate_medal",
    "commercial_state",
)


@dataclass
class GenerationMeta:
    generation_id: int
    status: str
    is_current: bool
    refresh_trigger: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    source_query_ms: Optional[int] = None
    crm_query_ms: Optional[int] = None
    cache_write_ms: Optional[int] = None
    error_summary: Optional[str] = None
    routing_version: Optional[str] = None
    registry_version: Optional[str] = None
    registry_hash: Optional[str] = None
    metrics_collected: int = 0


@dataclass
class SnapshotRow:
    snapshot_key: str
    metric_group: str
    metric_name: str
    metric_value: Optional[float] = None
    payload_json: Optional[Dict[str, Any]] = None
    source_contour: Optional[str] = None
    category_code: Optional[str] = None
    opportunity_track: Optional[str] = None
    medal_scope: Optional[str] = None
    commercial_state: Optional[str] = None
    data_as_of: Optional[datetime] = None


def cache_schema_ready(crm_db) -> bool:
    if crm_db is None:
        return False
    try:
        rows = crm_db.execute_query(
            "SELECT to_regclass('public.crm_v3_analytics_generations') IS NOT NULL AS ok"
        )
        if not rows:
            return False
        row = rows[0]
        ok = row.get("ok") if isinstance(row, dict) else row[0]
        if not ok:
            return False
        rows2 = crm_db.execute_query(
            "SELECT to_regclass('public.crm_v3_analytics_snapshots') IS NOT NULL AS ok"
        )
        row2 = rows2[0]
        ok2 = row2.get("ok") if isinstance(row2, dict) else row2[0]
        return bool(ok2)
    except Exception:
        return False


class InMemoryAnalyticsCache:
    """Test / pre-migration store. Same semantics as Postgres store."""

    def __init__(self) -> None:
        self.generations: Dict[int, GenerationMeta] = {}
        self.rows: Dict[int, List[SnapshotRow]] = {}
        self._next_id = 1
        self.s7_writes = 0
        self.runtime_ddl = 0

    def schema_ready(self) -> bool:
        return True

    def start_generation(self, trigger: str = "manual") -> GenerationMeta:
        gid = self._next_id
        self._next_id += 1
        meta = GenerationMeta(
            generation_id=gid,
            status="BUILDING",
            is_current=False,
            refresh_trigger=trigger,
            started_at=datetime.now(timezone.utc),
        )
        self.generations[gid] = meta
        self.rows[gid] = []
        return meta

    def write_rows(self, generation_id: int, rows: Sequence[SnapshotRow]) -> int:
        self.rows.setdefault(generation_id, []).extend(rows)
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
        for g in self.generations.values():
            if g.is_current:
                g.is_current = False
        meta = self.generations[generation_id]
        meta.status = "COMPLETE"
        meta.is_current = True
        meta.finished_at = datetime.now(timezone.utc)
        meta.duration_ms = duration_ms
        meta.source_query_ms = source_query_ms
        meta.crm_query_ms = crm_query_ms
        meta.cache_write_ms = cache_write_ms
        meta.routing_version = routing_version
        meta.registry_version = registry_version
        meta.registry_hash = registry_hash
        meta.metrics_collected = metrics_collected
        meta.error_summary = None
        return meta

    def fail_generation(self, generation_id: int, error: str, *, duration_ms: int = 0) -> GenerationMeta:
        meta = self.generations[generation_id]
        meta.status = "FAILED"
        meta.is_current = False
        meta.finished_at = datetime.now(timezone.utc)
        meta.duration_ms = duration_ms
        meta.error_summary = (error or "")[:2000]
        return meta

    def get_current_complete(self) -> Optional[GenerationMeta]:
        for g in sorted(self.generations.values(), key=lambda x: x.generation_id, reverse=True):
            if g.is_current and g.status == "COMPLETE":
                return g
        return None

    def get_latest_attempt(self) -> Optional[GenerationMeta]:
        if not self.generations:
            return None
        return self.generations[max(self.generations)]

    def load_rows(self, generation_id: int) -> List[SnapshotRow]:
        return list(self.rows.get(generation_id, []))

    def load_dashboard_payload(self, generation_id: int) -> Optional[Dict[str, Any]]:
        for row in self.rows.get(generation_id, []):
            if row.metric_group == "DASHBOARD" and row.metric_name == "snapshot":
                return dict(row.payload_json or {})
        return None


class PostgresAnalyticsCache:
    """CRM DB cache. Writes only to analytics tables. No DDL."""

    def __init__(self, crm_db) -> None:
        self.crm_db = crm_db
        self.s7_writes = 0
        self.runtime_ddl = 0

    def schema_ready(self) -> bool:
        return cache_schema_ready(self.crm_db)

    def start_generation(self, trigger: str = "manual") -> GenerationMeta:
        rows = self.crm_db.execute_query(
            """
            INSERT INTO crm_v3_analytics_generations (status, is_current, refresh_trigger)
            VALUES ('BUILDING', FALSE, %(t)s)
            RETURNING generation_id, status, is_current, refresh_trigger, started_at
            """,
            {"t": trigger},
        )
        row = rows[0]
        return GenerationMeta(
            generation_id=int(row["generation_id"] if isinstance(row, dict) else row[0]),
            status="BUILDING",
            is_current=False,
            refresh_trigger=trigger,
            started_at=row.get("started_at") if isinstance(row, dict) else None,
        )

    def write_rows(self, generation_id: int, rows: Sequence[SnapshotRow]) -> int:
        n = 0
        for r in rows:
            self.crm_db.execute_query(
                """
                INSERT INTO crm_v3_analytics_snapshots (
                    generation_id, snapshot_key, source_contour, category_code,
                    opportunity_track, medal_scope, commercial_state,
                    metric_group, metric_name, metric_value, payload_json, data_as_of
                ) VALUES (
                    %(gid)s, %(key)s, %(contour)s, %(cat)s, %(track)s, %(medal)s, %(life)s,
                    %(grp)s, %(name)s, %(val)s, %(payload)s::jsonb, COALESCE(%(asof)s, now())
                )
                ON CONFLICT (generation_id, snapshot_key, metric_group, metric_name)
                DO UPDATE SET
                    metric_value = EXCLUDED.metric_value,
                    payload_json = EXCLUDED.payload_json,
                    data_as_of = EXCLUDED.data_as_of
                """,
                {
                    "gid": generation_id,
                    "key": r.snapshot_key,
                    "contour": r.source_contour,
                    "cat": r.category_code,
                    "track": r.opportunity_track,
                    "medal": r.medal_scope,
                    "life": r.commercial_state,
                    "grp": r.metric_group,
                    "name": r.metric_name,
                    "val": r.metric_value,
                    "payload": json.dumps(r.payload_json or {}, ensure_ascii=False),
                    "asof": r.data_as_of,
                },
            )
            n += 1
        return n

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
        # Atomic switch: clear previous current, mark this COMPLETE+current
        self.crm_db.execute_query(
            """
            UPDATE crm_v3_analytics_generations
            SET is_current = FALSE
            WHERE is_current = TRUE AND generation_id <> %(gid)s
            """,
            {"gid": generation_id},
        )
        rows = self.crm_db.execute_query(
            """
            UPDATE crm_v3_analytics_generations
            SET status = 'COMPLETE',
                is_current = TRUE,
                finished_at = now(),
                duration_ms = %(dur)s,
                source_query_ms = %(src)s,
                crm_query_ms = %(crm)s,
                cache_write_ms = %(wrt)s,
                routing_version = %(rv)s,
                registry_version = %(regv)s,
                registry_hash = %(hash)s,
                metrics_collected = %(mc)s,
                error_summary = NULL
            WHERE generation_id = %(gid)s
            RETURNING generation_id, status, is_current, refresh_trigger,
                      started_at, finished_at, duration_ms, error_summary
            """,
            {
                "gid": generation_id,
                "dur": duration_ms,
                "src": source_query_ms,
                "crm": crm_query_ms,
                "wrt": cache_write_ms,
                "rv": routing_version,
                "regv": registry_version,
                "hash": registry_hash,
                "mc": metrics_collected,
            },
        )
        row = rows[0]
        return GenerationMeta(
            generation_id=generation_id,
            status="COMPLETE",
            is_current=True,
            refresh_trigger=row.get("refresh_trigger", "manual") if isinstance(row, dict) else "manual",
            finished_at=row.get("finished_at") if isinstance(row, dict) else None,
            duration_ms=duration_ms,
            metrics_collected=metrics_collected,
        )

    def fail_generation(self, generation_id: int, error: str, *, duration_ms: int = 0) -> GenerationMeta:
        self.crm_db.execute_query(
            """
            UPDATE crm_v3_analytics_generations
            SET status = 'FAILED',
                is_current = FALSE,
                finished_at = now(),
                duration_ms = %(dur)s,
                error_summary = %(err)s
            WHERE generation_id = %(gid)s
            """,
            {"gid": generation_id, "dur": duration_ms, "err": (error or "")[:2000]},
        )
        return GenerationMeta(
            generation_id=generation_id,
            status="FAILED",
            is_current=False,
            refresh_trigger="manual",
            duration_ms=duration_ms,
            error_summary=(error or "")[:2000],
        )

    def get_current_complete(self) -> Optional[GenerationMeta]:
        rows = self.crm_db.execute_query(
            """
            SELECT generation_id, status, is_current, refresh_trigger,
                   started_at, finished_at, duration_ms, source_query_ms,
                   crm_query_ms, cache_write_ms, error_summary,
                   routing_version, registry_version, registry_hash, metrics_collected
            FROM crm_v3_analytics_generations
            WHERE is_current = TRUE AND status = 'COMPLETE'
            ORDER BY generation_id DESC
            LIMIT 1
            """
        )
        if not rows:
            return None
        return self._meta_from_row(rows[0])

    def get_latest_attempt(self) -> Optional[GenerationMeta]:
        rows = self.crm_db.execute_query(
            """
            SELECT generation_id, status, is_current, refresh_trigger,
                   started_at, finished_at, duration_ms, source_query_ms,
                   crm_query_ms, cache_write_ms, error_summary,
                   routing_version, registry_version, registry_hash, metrics_collected
            FROM crm_v3_analytics_generations
            ORDER BY generation_id DESC
            LIMIT 1
            """
        )
        if not rows:
            return None
        return self._meta_from_row(rows[0])

    def load_dashboard_payload(self, generation_id: int) -> Optional[Dict[str, Any]]:
        rows = self.crm_db.execute_query(
            """
            SELECT payload_json
            FROM crm_v3_analytics_snapshots
            WHERE generation_id = %(gid)s
              AND metric_group = 'DASHBOARD'
              AND metric_name = 'snapshot'
              AND snapshot_key = 'global'
            LIMIT 1
            """,
            {"gid": generation_id},
        )
        if not rows:
            return None
        row = rows[0]
        payload = row.get("payload_json") if isinstance(row, dict) else row[0]
        if isinstance(payload, str):
            return json.loads(payload)
        return dict(payload or {})

    @staticmethod
    def _meta_from_row(row: Any) -> GenerationMeta:
        if not isinstance(row, dict):
            return GenerationMeta(
                generation_id=int(row[0]),
                status=str(row[1]),
                is_current=bool(row[2]),
                refresh_trigger=str(row[3]),
            )
        return GenerationMeta(
            generation_id=int(row["generation_id"]),
            status=str(row["status"]),
            is_current=bool(row["is_current"]),
            refresh_trigger=str(row.get("refresh_trigger") or "manual"),
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
            duration_ms=row.get("duration_ms"),
            source_query_ms=row.get("source_query_ms"),
            crm_query_ms=row.get("crm_query_ms"),
            cache_write_ms=row.get("cache_write_ms"),
            error_summary=row.get("error_summary"),
            routing_version=row.get("routing_version"),
            registry_version=row.get("registry_version"),
            registry_hash=row.get("registry_hash"),
            metrics_collected=int(row.get("metrics_collected") or 0),
        )
