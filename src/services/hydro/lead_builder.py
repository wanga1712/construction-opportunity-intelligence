"""Deterministic Hydro logical leads, suitable for dry-run or repository adapters."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import HydroLeadKind, HydroSourceObject


@dataclass
class HydroLeadCandidate:
    logical_key: str
    kind: HydroLeadKind
    company_key: str | None
    object_keys: list[str] = field(default_factory=list)
    state: str = "NEW"
    merged_into: str | None = None


def logical_lead_key(obj: HydroSourceObject) -> str:
    if obj.company_key:
        return f"hydro:company:{obj.company_key}"
    return f"hydro:object:{obj.identity_key}"


def build_candidates(objects: list[HydroSourceObject]) -> list[HydroLeadCandidate]:
    grouped: dict[str, HydroLeadCandidate] = {}
    for obj in objects:
        key = logical_lead_key(obj)
        lead = grouped.setdefault(key, HydroLeadCandidate(
            key, HydroLeadKind.COMPANY_CONTOUR if obj.company_key else HydroLeadKind.STANDALONE_OBJECT,
            obj.company_key,
        ))
        if obj.identity_key not in lead.object_keys:
            lead.object_keys.append(obj.identity_key)
    return list(grouped.values())


def merge_standalone(standalone: HydroLeadCandidate, company: HydroLeadCandidate) -> None:
    if standalone.kind is not HydroLeadKind.STANDALONE_OBJECT:
        raise ValueError("only STANDALONE_OBJECT can be merged")
    if company.kind is not HydroLeadKind.COMPANY_CONTOUR:
        raise ValueError("merge target must be COMPANY_CONTOUR")
    for key in standalone.object_keys:
        if key not in company.object_keys:
            company.object_keys.append(key)
    standalone.state = "MERGED"
    standalone.merged_into = company.logical_key
