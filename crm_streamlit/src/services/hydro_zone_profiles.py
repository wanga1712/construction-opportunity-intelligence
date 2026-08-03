"""Hydro applicability zones for CRM object cataloging."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from src.services.object_models import ObjectViewItem


@dataclass(frozen=True)
class HydroZoneProfile:
    code: str
    label: str
    keywords: tuple[str, ...]


HYDRO_ZONE_PROFILES: tuple[HydroZoneProfile, ...] = (
    HydroZoneProfile("roof", "Кровля", ("кровл", "мембран", "покрыти", "протечк крыши")),
    HydroZoneProfile("facade", "Фасад", ("фасад", "межпанель", "герметизац", "стык панел")),
    HydroZoneProfile("foundation", "Фундамент", ("фундамент", "цокол", "подземн", "грунтов")),
    HydroZoneProfile("basement", "Подвал/паркинг", ("подвал", "паркинг", "подзем", "деформацион", "шов")),
    HydroZoneProfile("road_drainage", "Дороги/водоотвод", ("дренаж", "водоотвод", "ливнев", "лоток", "коллектор")),
    HydroZoneProfile("utility_inlet", "Вводы/коммуникации", ("ввод", "узел", "технологическ", "трубопровод", "инъекц")),
)


def detect_hydro_zones(item: ObjectViewItem) -> List[str]:
    text = " ".join(
        str(x or "")
        for x in (item.name, item.address, item.region, item.search_text, item.ai_priority_reason)
    ).lower()
    zones: list[str] = []
    for profile in HYDRO_ZONE_PROFILES:
        if any(k in text for k in profile.keywords):
            zones.append(profile.code)
    return zones


def hydro_zone_labels(codes: Iterable[str]) -> List[str]:
    lookup = {x.code: x.label for x in HYDRO_ZONE_PROFILES}
    return [lookup[c] for c in codes if c in lookup]

