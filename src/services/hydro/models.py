"""Small, persistence-neutral Hydro contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class HydroLeadKind(StrEnum):
    COMPANY_CONTOUR = "COMPANY_CONTOUR"
    STANDALONE_OBJECT = "STANDALONE_OBJECT"


@dataclass(frozen=True)
class HydroSourceObject:
    source_object_id: str
    cadastral_number: str | None = None
    external_object_id: str | None = None
    name: str | None = None
    purpose: str | None = None
    object_type: str | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    floors_underground: int | None = None
    floors_total: int | None = None
    construction_finish_year: int | None = None
    commissioning_year: int | None = None
    area_total: float | None = None
    wall_material: str | None = None
    parking_type: str | None = None
    parking_confidence: float | None = None
    parking_candidate_reason: str | None = None
    management_status: str | None = None
    management_type: str | None = None
    management_company_source_id: str | None = None
    management_company_name: str | None = None
    management_company_inn: str | None = None
    management_company_ogrn: str | None = None
    management_company_phone: str | None = None
    source_updated_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    synced_at: datetime | None = None
    source_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def identity_key(self) -> str:
        return f"NSPD_PARKING:{self.source_object_id}"

    @property
    def company_key(self) -> str | None:
        return self.management_company_ogrn or self.management_company_inn or self.management_company_source_id


def source_row_to_object(row: dict[str, Any], *, now: datetime | None = None) -> HydroSourceObject:
    """Map the verified NSPD row without inventing missing facts."""
    source_id = row.get("source_object_id", row.get("id"))
    if source_id in (None, ""):
        raise ValueError("source_object_id is required")
    return HydroSourceObject(
        source_object_id=str(source_id), external_object_id=row.get("external_object_id"),
        cadastral_number=row.get("cadastral_number"), name=row.get("name"),
        purpose=row.get("purpose"), object_type=row.get("object_type"),
        address=row.get("address", row.get("address_text")), lat=row.get("lat"), lon=row.get("lon"),
        floors_underground=row.get("floors_underground"), floors_total=row.get("floors_total"),
        construction_finish_year=row.get("construction_finish_year"),
        commissioning_year=row.get("commissioning_year"), area_total=row.get("area_total"),
        wall_material=row.get("wall_material"), parking_type=row.get("parking_type"),
        parking_confidence=row.get("confidence_score"), parking_candidate_reason=row.get("candidate_reason"),
        management_status=row.get("uk_status", row.get("management_status")),
        management_type=row.get("management_type"),
        management_company_source_id=str(row["uk_id"]) if row.get("uk_id") is not None else None,
        management_company_name=row.get("uk_name"), management_company_inn=row.get("uk_inn"),
        management_company_ogrn=row.get("uk_ogrn"), management_company_phone=row.get("uk_phone"),
        source_updated_at=row.get("source_updated_at", row.get("updated_at")),
        first_seen_at=row.get("first_seen_at", now), last_seen_at=now, synced_at=now,
        source_payload=dict(row),
    )
