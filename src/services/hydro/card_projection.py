"""UI-neutral Hydro lead cards projected from canonical CRM rows."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from .scoring import ScoreResult

@dataclass(frozen=True)
class HydroObjectCardDTO:
    object_id: int | str
    cadastral_number: str | None
    address: str | None
    area_total: float | None
    floors_underground: int | None
    parking_type: str | None
    lat: float | None
    lon: float | None
    potential: ScoreResult
    missing_facts: tuple[str, ...]

@dataclass(frozen=True)
class HydroLeadCardDTO:
    lead_id: int | str
    lead_kind: str
    state: str
    company_name: str | None
    company_inn: str | None
    company_ogrn: str | None
    company_phone: str | None
    object_count: int
    top_objects: tuple[HydroObjectCardDTO, ...]
    potential: ScoreResult
    readiness: ScoreResult
    source_health: str
    source_last_success_at: datetime | None
    merged_into_lead_id: int | str | None = None
    logical_key: str | None = None

    @property
    def company_resolved(self) -> bool:
        return bool(self.company_name or self.company_inn or self.company_ogrn)

    @property
    def next_task_label(self) -> str | None:
        return "определить управляющую организацию" if self.lead_kind == "STANDALONE_OBJECT" and not self.company_resolved else None

def _score(raw: Any, default: ScoreResult) -> ScoreResult:
    if isinstance(raw, ScoreResult): return raw
    raw = raw or {}
    return ScoreResult(int(raw.get("score", default.score)), str(raw.get("grade", default.grade)), tuple(raw.get("reasons", ())), tuple(raw.get("missing_signals", ())), str(raw.get("version", default.version)))

def missing_facts(row: dict[str, Any]) -> tuple[str, ...]:
    labels = (("address", "адрес"), ("area_total", "площадь"), ("floors_underground", "подземные этажи"), ("parking_type", "тип паркинга"))
    return tuple(label for key, label in labels if row.get(key) in (None, ""))

def object_card(row: dict[str, Any]) -> HydroObjectCardDTO:
    default = ScoreResult(0, "D", (), (), "hydro_object_potential_v1")
    return HydroObjectCardDTO(row.get("object_id", row.get("parking_object_id")), row.get("cadastral_number"), row.get("address"), row.get("area_total"), row.get("floors_underground"), row.get("parking_type"), row.get("lat"), row.get("lon"), _score(row.get("object_potential"), default), missing_facts(row))

def lead_card(row: dict[str, Any], objects: list[dict[str, Any]] | None = None) -> HydroLeadCardDTO:
    obj_rows = objects if objects is not None else row.get("objects", [])
    default = ScoreResult(0, "D", (), (), "hydro_object_potential_v1")
    readiness = ScoreResult(0, "D", (), (), "hydro_lead_readiness_v1")
    cards = tuple(object_card(item) for item in obj_rows)
    return HydroLeadCardDTO(row.get("lead_id", row.get("id")), str(row.get("lead_kind", "")), str(row.get("state", row.get("hydro_state", "NEW"))), row.get("company_name"), row.get("company_inn"), row.get("company_ogrn"), row.get("company_phone"), int(row.get("object_count", len(cards))), cards, _score(row.get("object_potential"), default), _score(row.get("lead_readiness"), readiness), str(row.get("source_health", "NEVER_SYNCED")), row.get("source_last_success_at"), row.get("merged_into_lead_id"), row.get("logical_key"))
