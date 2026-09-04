"""Independent deterministic Hydro scores."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .models import HydroSourceObject


@dataclass(frozen=True)
class ScoreResult:
    score: int
    grade: str
    reasons: tuple[str, ...]
    missing_signals: tuple[str, ...]
    version: str


def _grade(score: int) -> str:
    return "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 35 else "D"


def object_potential(obj: HydroSourceObject, *, problem_evidence: bool = False) -> ScoreResult:
    score, reasons, missing = 0, [], []
    if (obj.floors_underground or 0) >= 2: score += 30; reasons.append("underground_floors>=2")
    elif obj.floors_underground == 1: score += 18; reasons.append("underground_floors=1")
    else: missing.append("underground_floors")
    if obj.parking_type == "UNDERGROUND": score += 25; reasons.append("underground_parking")
    elif obj.parking_type is None: missing.append("parking_type")
    if obj.parking_confidence is not None: score += min(15, round(max(0, obj.parking_confidence) * 15)); reasons.append("parking_confidence")
    else: missing.append("parking_confidence")
    if obj.area_total and obj.area_total >= 1000: score += 12; reasons.append("area>=1000")
    elif obj.area_total is None: missing.append("area_total")
    year = obj.commissioning_year or obj.construction_finish_year
    if year and date.today().year - year >= 20: score += 10; reasons.append("age>=20y")
    elif year is None: missing.append("building_year")
    if problem_evidence: score += 8; reasons.append("factual_problem_evidence")
    return ScoreResult(min(100, score), _grade(min(100, score)), tuple(reasons), tuple(missing), "hydro_object_potential_v1")


def lead_readiness(facts: dict[str, Any]) -> ScoreResult:
    checks = (("company_resolved", 20), ("usable_phone", 10), ("technical_contact", 15),
              ("meeting", 15), ("problem_confirmed", 15), ("access", 10),
              ("documents", 5), ("survey", 5), ("proposal", 3), ("next_action", 2))
    score, reasons, missing = 0, [], []
    for key, weight in checks:
        value = facts.get(key)
        if value is True: score += weight; reasons.append(key)
        elif value is None: missing.append(key)
    score = min(100, score)
    return ScoreResult(score, _grade(score), tuple(reasons), tuple(missing), "hydro_lead_readiness_v1")
