"""Idempotent canonical source feed contract with outage-safe state."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import HydroSourceObject


@dataclass
class SourceHealth:
    source: str = "NSPD_PARKING"
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    status: str = "NEVER_SYNCED"
    rows_seen: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    rows_invalid: int = 0
    safe_error_class: str | None = None
    safe_error_message: str | None = None


@dataclass
class CanonicalHydroStore:
    objects: dict[str, HydroSourceObject] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)
    health: SourceHealth = field(default_factory=SourceHealth)

    def sync(self, rows: list[HydroSourceObject], *, now: datetime | None = None) -> SourceHealth:
        now = now or datetime.now(timezone.utc)
        h = SourceHealth(source=self.health.source, last_attempt_at=now, status="SUCCESS", rows_seen=len(rows))
        for obj in rows:
            try:
                key = obj.identity_key
                digest = hashlib.sha256(json.dumps(obj.source_payload, sort_keys=True, default=str).encode()).hexdigest()
                if key not in self.objects:
                    h.rows_inserted += 1
                elif self.hashes.get(key) != digest:
                    h.rows_updated += 1
                else:
                    h.rows_unchanged += 1
                self.objects[key] = obj
                self.hashes[key] = digest
            except (TypeError, ValueError):
                h.rows_invalid += 1
        h.status = "PARTIAL" if h.rows_invalid else "SUCCESS"
        h.last_success_at = now
        self.health = h
        return h

    def source_failed(self, error: Exception, *, now: datetime | None = None) -> SourceHealth:
        old = self.health
        self.health = SourceHealth(source=old.source, last_attempt_at=now or datetime.now(timezone.utc),
                                   last_success_at=old.last_success_at, status="FAILED",
                                   rows_seen=old.rows_seen, rows_inserted=old.rows_inserted,
                                   rows_updated=old.rows_updated, rows_unchanged=old.rows_unchanged,
                                   rows_invalid=old.rows_invalid, safe_error_class=type(error).__name__,
                                   safe_error_message=str(error)[:300])
        return self.health
