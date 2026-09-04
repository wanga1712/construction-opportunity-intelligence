"""Hydro projection over canonical CRM-side state; never calls source DB."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .lead_builder import HydroLeadCandidate
from .models import HydroSourceObject
from .scoring import ScoreResult, lead_readiness, object_potential


@dataclass(frozen=True)
class HydroLeadProjection:
    lead_key: str
    lead_kind: str
    state: str
    management_company: dict[str, Any] | None
    object_count: int
    strong_object_count: int
    top_objects: tuple[dict[str, Any], ...]
    object_potential: ScoreResult
    lead_readiness: ScoreResult
    source_freshness: datetime | None
    source_health: str
    merged_into: str | None = None


def project(lead: HydroLeadCandidate, objects: dict[str, HydroSourceObject], *, health: str = "SUCCESS", freshness: datetime | None = None, readiness: dict[str, Any] | None = None) -> HydroLeadProjection:
    rows = [objects[key] for key in lead.object_keys if key in objects]
    scored = [(obj, object_potential(obj)) for obj in rows]
    scored.sort(key=lambda pair: pair[1].score, reverse=True)
    top = tuple({**asdict(obj), "identity_key": obj.identity_key, "potential": asdict(score)} for obj, score in scored[:5])
    best = scored[0][1] if scored else ScoreResult(0, "D", (), ("object",), "hydro_object_potential_v1")
    company = None
    if lead.company_key and rows:
        obj = rows[0]
        company = {"key": lead.company_key, "name": obj.management_company_name, "inn": obj.management_company_inn, "ogrn": obj.management_company_ogrn}
    return HydroLeadProjection(lead.logical_key, lead.kind.value, lead.state, company, len(rows), sum(s.score >= 60 for _, s in scored), top, best, lead_readiness(readiness or {}), freshness, health, lead.merged_into)
