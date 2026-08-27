"""Controlled expert object taxonomy for staged annotation (config authority).

Hierarchy: OBJECT_SECTOR → OBJECT_TYPE → optional OBJECT_SUBTYPE.

Canonical vocabulary lives here (not MODEL RAW). Prior HUMAN expert values may
appear as suggestions only via collect_expert_* helpers.
"""
from __future__ import annotations

from typing import Any

OBJECT_SECTOR_FIELD = "expert_object_sector"
OBJECT_TYPE_FIELD = "expert_object_type"
OBJECT_SUBTYPE_FIELD = "expert_object_subtype"

SOCIAL = "SOCIAL"
RESIDENTIAL = "RESIDENTIAL"
COMMERCIAL = "COMMERCIAL"
INDUSTRIAL = "INDUSTRIAL"
INFRASTRUCTURE = "INFRASTRUCTURE"
OTHER = "OTHER"
UNCERTAIN = "UNCERTAIN"

OBJECT_SECTOR_VALUES = (
    SOCIAL,
    RESIDENTIAL,
    COMMERCIAL,
    INDUSTRIAL,
    INFRASTRUCTURE,
    OTHER,
    UNCERTAIN,
)

OBJECT_SECTOR_LABELS_RU = {
    SOCIAL: "Социальный объект",
    RESIDENTIAL: "Жилой объект",
    COMMERCIAL: "Коммерческий объект",
    INDUSTRIAL: "Промышленный объект",
    INFRASTRUCTURE: "Инфраструктура",
    OTHER: "Другое",
    UNCERTAIN: "Не уверен",
}

# code → Russian label. Codes are stable; labels are operator-facing.
OBJECT_TYPES_BY_SECTOR: dict[str, list[tuple[str, str]]] = {
    SOCIAL: [
        ("KINDERGARTEN", "Детский сад"),
        ("SCHOOL", "Школа"),
        ("HOSPITAL", "Больница"),
        ("POLYCLINIC", "Поликлиника"),
        ("SPORTS_FACILITY", "Спортивный объект"),
        ("SOCIAL_ADMIN", "Административное социальное учреждение"),
        ("CULTURE_FACILITY", "Объект культуры"),
        ("OTHER_SOCIAL", "Другой социальный объект"),
    ],
    RESIDENTIAL: [
        ("APARTMENT_BUILDING", "Многоквартирный жилой дом"),
        ("RESIDENTIAL_COMPLEX", "Жилой комплекс"),
        ("DORMITORY", "Общежитие"),
        ("OTHER_RESIDENTIAL", "Другой жилой объект"),
    ],
    COMMERCIAL: [
        ("HOTEL", "Гостиница"),
        ("SHOPPING_CENTER", "Торговый центр"),
        ("OFFICE", "Офис"),
        ("RESTAURANT", "Ресторан / общепит"),
        ("WAREHOUSE", "Склад / логистический объект"),
        ("OTHER_COMMERCIAL", "Другой коммерческий объект"),
    ],
    INDUSTRIAL: [
        ("FACTORY", "Завод"),
        ("PRODUCTION_BUILDING", "Производственный корпус"),
        ("ENERGY_FACILITY", "Энергетический объект"),
        ("OTHER_INDUSTRIAL", "Другой промышленный объект"),
    ],
    INFRASTRUCTURE: [
        ("ROAD", "Дорога"),
        ("BRIDGE", "Мост"),
        ("UTILITY_NETWORKS", "Инженерные сети"),
        ("MUNICIPAL_INFRASTRUCTURE", "Коммунальная инфраструктура"),
        ("ENERGY_INFRASTRUCTURE", "Энергетическая инфраструктура"),
        ("OTHER_INFRASTRUCTURE", "Другая инфраструктура"),
    ],
    OTHER: [
        ("OTHER_OBJECT", "Иной объект"),
    ],
    UNCERTAIN: [
        ("UNCERTAIN_OBJECT", "Не уверен / объект неясен"),
    ],
}

# Optional finer subtypes (code, label) keyed by object type code.
OBJECT_SUBTYPES_BY_TYPE: dict[str, list[tuple[str, str]]] = {
    "APARTMENT_BUILDING": [
        ("NEW_BUILD", "Новое строительство"),
        ("CAPITAL_REPAIR", "Капитальный ремонт"),
        ("UNDERGROUND_PART", "Подземная часть"),
    ],
    "SCHOOL": [
        ("SCHOOL_BUILDING", "Здание школы"),
        ("SCHOOL_CAMPUS", "Школьный комплекс"),
    ],
    "ROAD": [
        ("ROAD_PAVEMENT", "Дорожное покрытие"),
        ("ROAD_REPAIR", "Ремонт дороги"),
    ],
}


def object_sector_of(payload: dict | None) -> str | None:
    if not payload:
        return None
    value = payload.get(OBJECT_SECTOR_FIELD)
    return value if value in OBJECT_SECTOR_VALUES else None


def object_type_of(payload: dict | None) -> str | None:
    if not payload:
        return None
    value = str(payload.get(OBJECT_TYPE_FIELD) or "").strip()
    return value or None


def object_subtype_of(payload: dict | None) -> str | None:
    if not payload:
        return None
    value = str(payload.get(OBJECT_SUBTYPE_FIELD) or "").strip()
    return value or None


def object_type_options(sector: str | None) -> list[tuple[str, str]]:
    if not sector:
        return []
    return list(OBJECT_TYPES_BY_SECTOR.get(sector, []))


def object_subtype_options(object_type: str | None) -> list[tuple[str, str]]:
    if not object_type:
        return []
    return list(OBJECT_SUBTYPES_BY_TYPE.get(object_type, []))


def object_type_label(code_or_text: str | None) -> str | None:
    if not code_or_text:
        return None
    for pairs in OBJECT_TYPES_BY_SECTOR.values():
        for code, label in pairs:
            if code == code_or_text:
                return label
    return code_or_text


def object_subtype_label(code_or_text: str | None) -> str | None:
    if not code_or_text:
        return None
    for pairs in OBJECT_SUBTYPES_BY_TYPE.values():
        for code, label in pairs:
            if code == code_or_text:
                return label
    return code_or_text


def object_sector_label(sector: str | None) -> str | None:
    if not sector:
        return None
    return OBJECT_SECTOR_LABELS_RU.get(sector, sector)


def object_summary_label(payload: dict | None) -> str | None:
    """Compact human label for card summary."""
    if not payload:
        return None
    sector = object_sector_of(payload)
    obj_type = object_type_of(payload)
    type_label = object_type_label(obj_type)
    sector_label = object_sector_label(sector)
    if type_label and type_label != obj_type:
        return type_label
    if type_label:
        return type_label
    return sector_label


def taxonomy_stats() -> dict[str, int]:
    types = sum(len(v) for v in OBJECT_TYPES_BY_SECTOR.values())
    subtypes = sum(len(v) for v in OBJECT_SUBTYPES_BY_TYPE.values())
    return {
        "sectors": len(OBJECT_SECTOR_VALUES),
        "types": types,
        "subtypes": subtypes,
    }


def model_object_hints(assessment: dict | None) -> dict[str, str | None]:
    """Read-only model object hints — never auto-accepted into human fields."""
    if not assessment:
        return {"sector": None, "object_type": None, "object_subtype": None}
    nr = assessment.get("normalized_result") or {}
    oc = nr.get("object_classification") if isinstance(nr.get("object_classification"), dict) else {}
    return {
        "sector": oc.get("object_sector") or nr.get("object_sector"),
        "object_type": (
            oc.get("object_type")
            or nr.get("object_type")
            or assessment.get("proposed_object_type")
        ),
        "object_subtype": oc.get("object_subtype") or nr.get("object_subtype"),
    }
