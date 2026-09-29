"""Canonical expert object taxonomy: OBJECT_SECTOR -> OBJECT_TYPE -> OBJECT_SUBTYPE.

WIP=OBJECT-TAXONOMY-CANONICAL-IMPLEMENTATION-V1.

This module is the single authority for the project object vocabulary. Routing,
first-pass resolvers, UI selectors and reporting read the codes declared here;
no other module may invent object sector / type / subtype strings.

Contract
--------
* Ad-hoc vocabularies that grew up in routing and in model output are legacy
  *inputs*: TRANSPORT_INFRASTRUCTURE, UTILITY_INFRASTRUCTURE,
  SOCIAL_INFRASTRUCTURE, HEALTHCARE, GENERAL_CONSTRUCTION, GAS_PIPELINE,
  BUILDING_OR_STRUCTURE, "UNKNOWN" and DB free text. They normalize through
  LEGACY_OBJECT_ALIASES / LEGACY_RUSSIAN_OBJECT_TYPES and are never emitted as
  canonical output.
* Transport and utility infrastructure are not sectors of their own: they are
  INFRASTRUCTURE types and subtypes.
* Products are never object types. Benches, urns, MAF, lighting poles,
  playground equipment, curbstone or surfacing are commercial opportunities
  (product categories), not OBJECT_TYPE.
* A direct goods purchase has no object: use object_axes_for_direct_supply(),
  which returns N/A on all three axes.
* Prior HUMAN expert values may appear as suggestions only via collect_expert_* helpers.

Size note: tables and resolvers stay in one file on purpose. Splitting the
vocabulary out would recreate the second parallel enum this WIP removes.
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
URBAN_IMPROVEMENT = "URBAN_IMPROVEMENT"
OTHER = "OTHER"
UNCERTAIN = "UNCERTAIN"

OBJECT_SECTOR_VALUES = (
    SOCIAL,
    RESIDENTIAL,
    COMMERCIAL,
    INDUSTRIAL,
    INFRASTRUCTURE,
    URBAN_IMPROVEMENT,
    OTHER,
    UNCERTAIN,
)

OBJECT_SECTOR_LABELS_RU = {
    SOCIAL: "Социальный объект",
    RESIDENTIAL: "Жилой объект",
    COMMERCIAL: "Коммерческий объект",
    INDUSTRIAL: "Промышленный объект",
    INFRASTRUCTURE: "Инфраструктура",
    URBAN_IMPROVEMENT: "Благоустройство",
    OTHER: "Другое",
    UNCERTAIN: "Не уверен",
}

# code -> Russian label. Codes are stable; labels are operator-facing.
OBJECT_TYPES_BY_SECTOR: dict[str, list[tuple[str, str]]] = {
    SOCIAL: [
        ("KINDERGARTEN", "Детский сад"),
        ("SCHOOL", "Школа"),
        ("HOSPITAL", "Больница"),
        ("POLYCLINIC", "Поликлиника"),
        ("DISPENSARY", "Диспансер"),
        ("UNIVERSITY", "ВУЗ / университет"),
        ("SPORTS_FACILITY", "Спортивный объект"),
        ("SOCIAL_ADMIN", "Административное социальное учреждение"),
        ("CULTURE_FACILITY", "Объект культуры"),
        ("SOCIAL_CARE", "Учреждение социального обслуживания"),
        ("OTHER_SOCIAL", "Другой социальный объект"),
    ],
    RESIDENTIAL: [
        ("APARTMENT_BUILDING", "Многоквартирный жилой дом"),
        ("RESIDENTIAL_COMPLEX", "Жилой комплекс"),
        ("RESIDENTIAL_UNIT", "Квартира / жилое помещение"),
        ("DORMITORY", "Общежитие"),
        ("OTHER_RESIDENTIAL", "Другой жилой объект"),
    ],
    COMMERCIAL: [
        ("HOTEL", "Гостиница"),
        ("SHOPPING_CENTER", "Торговый центр"),
        ("OFFICE", "Офис"),
        ("RESTAURANT", "Ресторан / общепит"),
        ("WAREHOUSE", "Склад / логистический объект"),
        ("PARKING", "Парковка / паркинг"),
        ("OTHER_COMMERCIAL", "Другой коммерческий объект"),
    ],
    INDUSTRIAL: [
        ("FACTORY", "Завод"),
        ("PRODUCTION_BUILDING", "Производственный корпус"),
        ("ENERGY_FACILITY", "Энергетический объект"),
        ("INDUSTRIAL_SITE", "Промышленная площадка"),
        ("OTHER_INDUSTRIAL", "Другой промышленный объект"),
    ],
    INFRASTRUCTURE: [
        ("ROAD", "Дорога"),
        ("STREET", "Улица"),
        ("BRIDGE", "Мост"),
        ("TUNNEL", "Тоннель"),
        ("INTERCHANGE", "Транспортная развязка"),
        ("RAILWAY", "Железная дорога"),
        ("AIRPORT", "Аэропорт"),
        ("TRANSPORT_HUB", "Транспортный узел"),
        ("UTILITY_NETWORKS", "Инженерные сети"),
        ("MUNICIPAL_INFRASTRUCTURE", "Коммунальная инфраструктура"),
        ("ENERGY_INFRASTRUCTURE", "Энергетическая инфраструктура"),
        ("OTHER_INFRASTRUCTURE", "Другая инфраструктура"),
    ],
    URBAN_IMPROVEMENT: [
        ("PARK", "Парк"),
        ("SQUARE", "Сквер"),
        ("COURTYARD", "Дворовая территория"),
        ("EMBANKMENT", "Набережная"),
        ("PUBLIC_SPACE", "Общественное пространство"),
        ("PEDESTRIAN_ZONE", "Пешеходная зона"),
        ("STREETSCAPE", "Уличное благоустройство"),
        ("PLAYGROUND", "Детская / спортивная площадка"),
        ("GREEN_AREA", "Озеленение"),
        ("OTHER_URBAN_IMPROVEMENT", "Другое благоустройство"),
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
    "UTILITY_NETWORKS": [
        ("HEATING_NETWORK", "Тепловая сеть"),
        ("WATER_NETWORK", "Водопровод"),
        ("SEWER_NETWORK", "Канализация"),
        ("POWER_NETWORK", "Электросеть"),
        ("GAS_NETWORK", "Газопровод"),
        ("COMMUNICATION_NETWORK", "Сети связи"),
    ],
}

# Derived lookups. The tables above stay the single source of truth.
OBJECT_TYPE_TO_SECTOR: dict[str, str] = {
    code: sector
    for sector, pairs in OBJECT_TYPES_BY_SECTOR.items()
    for code, _label in pairs
}
ALL_OBJECT_TYPES: frozenset[str] = frozenset(OBJECT_TYPE_TO_SECTOR)

# Sentinel for "this procurement has no object at all" (direct supply).
OBJECT_NOT_APPLICABLE = "N/A"

# Model / legacy markers meaning "not an object procurement".
NON_OBJECT_MARKERS = frozenset({"SUPPLY", "GOODS", "WORKS", "N/A", "NA", "NONE"})

# --- OBJECT_CONTEXT / APPLICATION_AREA (crm_taxonomy_dimensions) -------------
# OBJECT_CONTEXT = in what environment the object sits (territory context).
# APPLICATION_AREA = which part of the object is touched. Kept as separate axes.
OBJECT_CONTEXT_DIMENSION = "OBJECT_CONTEXT"
APPLICATION_AREA_DIMENSION = "APPLICATION_AREA"

OBJECT_CONTEXT_TERMS: tuple[tuple[str, str], ...] = (
    ("roof", "Кровля (объект)"),
    ("landscaping", "Озеленение и благоустройство территории"),
    ("courtyard", "Дворовая территория"),
    ("external_territory", "Прилегающая территория"),
    ("parking_area", "Парковочная зона"),
)

APPLICATION_AREA_TERMS: tuple[tuple[str, str], ...] = (
    ("roof", "Кровля"),
    ("basement", "Подвал"),
    ("facade", "Фасад"),
)

# --- Legacy / ad-hoc vocabulary (input only, never canonical output) --------
# legacy sector or type name -> canonical (sector, type, subtype)
LEGACY_OBJECT_ALIASES: dict[str, tuple[str, str | None, str | None]] = {
    "TRANSPORT_INFRASTRUCTURE": (INFRASTRUCTURE, None, None),
    "ROAD_INFRASTRUCTURE": (INFRASTRUCTURE, "ROAD", None),
    "BRIDGE_INFRASTRUCTURE": (INFRASTRUCTURE, "BRIDGE", None),
    "UTILITY_INFRASTRUCTURE": (INFRASTRUCTURE, "UTILITY_NETWORKS", None),
    "SOCIAL_INFRASTRUCTURE": (SOCIAL, None, None),
    "SOCIAL_OBJECTS": (SOCIAL, None, None),
    "HEALTHCARE": (SOCIAL, None, None),
    "GENERAL_CONSTRUCTION": (OTHER, "OTHER_OBJECT", None),
    "CONSTRUCTION": (OTHER, "OTHER_OBJECT", None),
    "BUILDING_AND_CONSTRUCTION": (OTHER, "OTHER_OBJECT", None),
    "CONSTRUCTION_INFRASTRUCTURE": (INFRASTRUCTURE, None, None),
    "IMPROVEMENT_LANDSCAPING": (URBAN_IMPROVEMENT, None, None),
    "GAS_PIPELINE": (INFRASTRUCTURE, "UTILITY_NETWORKS", "GAS_NETWORK"),
    "BUILDING_OR_STRUCTURE": (OTHER, "OTHER_OBJECT", None),
}

# Legacy DB free text (crm_object_ai_classifications.object_type). Read-only
# normalization of values already stored; no inference and no writes.
LEGACY_RUSSIAN_OBJECT_TYPES: dict[str, tuple[str, str | None, str | None]] = {
    "дорога": (INFRASTRUCTURE, "ROAD", None),
    "улица": (INFRASTRUCTURE, "STREET", None),
    "мост": (INFRASTRUCTURE, "BRIDGE", None),
    "теплосеть": (INFRASTRUCTURE, "UTILITY_NETWORKS", "HEATING_NETWORK"),
    "водопровод": (INFRASTRUCTURE, "UTILITY_NETWORKS", "WATER_NETWORK"),
    "канализация": (INFRASTRUCTURE, "UTILITY_NETWORKS", "SEWER_NETWORK"),
    "газопровод": (INFRASTRUCTURE, "UTILITY_NETWORKS", "GAS_NETWORK"),
    "мкд": (RESIDENTIAL, "APARTMENT_BUILDING", None),
    "школа": (SOCIAL, "SCHOOL", None),
    "детский сад": (SOCIAL, "KINDERGARTEN", None),
    "больница": (SOCIAL, "HOSPITAL", None),
    "поликлиника": (SOCIAL, "POLYCLINIC", None),
    "общежитие": (RESIDENTIAL, "DORMITORY", None),
    "офис": (COMMERCIAL, "OFFICE", None),
    "гостиница": (COMMERCIAL, "HOTEL", None),
    "склад": (COMMERCIAL, "WAREHOUSE", None),
    "парк": (URBAN_IMPROVEMENT, "PARK", None),
    "сквер": (URBAN_IMPROVEMENT, "SQUARE", None),
    "дворовые территории": (URBAN_IMPROVEMENT, "COURTYARD", None),
    "котельная": (INDUSTRIAL, "ENERGY_FACILITY", None),
}


def _norm(value: Any) -> str:
    return str(value or "").strip()


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


def is_canonical_sector(value: Any) -> bool:
    return _norm(value).upper() in OBJECT_SECTOR_VALUES


def is_canonical_object_type(value: Any, sector: str | None = None) -> bool:
    code = _norm(value).upper()
    if code not in OBJECT_TYPE_TO_SECTOR:
        return False
    return not sector or OBJECT_TYPE_TO_SECTOR[code] == _norm(sector).upper()


def is_canonical_object_subtype(value: Any, object_type: str | None = None) -> bool:
    code = _norm(value).upper()
    if not code:
        return False
    if object_type:
        pairs = OBJECT_SUBTYPES_BY_TYPE.get(_norm(object_type).upper(), [])
        return code in {c for c, _ in pairs}
    return any(code in {c for c, _ in pairs} for pairs in OBJECT_SUBTYPES_BY_TYPE.values())


def sector_of_object_type(object_type: Any) -> str | None:
    return OBJECT_TYPE_TO_SECTOR.get(_norm(object_type).upper())


def types_of_sector(sector: Any) -> tuple[str, ...]:
    pairs = OBJECT_TYPES_BY_SECTOR.get(_norm(sector).upper(), [])
    return tuple(code for code, _label in pairs)


def all_object_types() -> frozenset[str]:
    return ALL_OBJECT_TYPES


def object_context_terms() -> tuple[tuple[str, str], ...]:
    return OBJECT_CONTEXT_TERMS


def application_area_terms() -> tuple[tuple[str, str], ...]:
    return APPLICATION_AREA_TERMS


def canonical_object_sector(value: Any) -> str | None:
    """Canonical sector code, or None when the value is not (legacy) mappable."""
    raw = _norm(value).upper()
    if not raw:
        return None
    if raw in OBJECT_SECTOR_VALUES:
        return raw
    mapped = LEGACY_OBJECT_ALIASES.get(raw)
    return mapped[0] if mapped else None


def canonical_object_type(value: Any) -> str | None:
    raw = _norm(value).upper()
    if not raw:
        return None
    if raw in OBJECT_TYPE_TO_SECTOR:
        return raw
    mapped = LEGACY_OBJECT_ALIASES.get(raw)
    return mapped[1] if mapped else None


def canonical_object_subtype(value: Any, object_type: Any = None) -> str | None:
    raw = _norm(value).upper()
    if not raw:
        return None
    if is_canonical_object_subtype(raw, object_type if object_type else None):
        return raw
    mapped = LEGACY_OBJECT_ALIASES.get(raw)
    if mapped and mapped[2]:
        return mapped[2]
    return raw if is_canonical_object_subtype(raw) else None


def normalize_object_axes(
    payload: dict | None = None,
    *,
    sector: Any = None,
    object_type: Any = None,
    object_subtype: Any = None,
) -> dict[str, str | None]:
    """Normalize legacy / model / free-text object values to canonical codes.

    Returns field-keyed dict (OBJECT_SECTOR_FIELD / OBJECT_TYPE_FIELD /
    OBJECT_SUBTYPE_FIELD). Unknown input yields None, never a fabricated code.
    """
    src = payload or {}
    raw_sector = sector if sector is not None else src.get(OBJECT_SECTOR_FIELD)
    raw_type = object_type if object_type is not None else src.get(OBJECT_TYPE_FIELD)
    raw_subtype = (
        object_subtype if object_subtype is not None else src.get(OBJECT_SUBTYPE_FIELD)
    )

    # A legacy *sector* name (e.g. TRANSPORT_INFRASTRUCTURE, SOCIAL_INFRASTRUCTURE)
    # may arrive in the object_type slot of old rows / model echoes; accept it.
    sec = canonical_object_sector(raw_sector) or canonical_object_sector(raw_type)
    typ = canonical_object_type(raw_type)
    legacy_subtype: str | None = None

    type_alias = LEGACY_OBJECT_ALIASES.get(_norm(raw_type).upper())
    if type_alias:
        legacy_subtype = type_alias[2]

    if typ is None:
        mapped = LEGACY_RUSSIAN_OBJECT_TYPES.get(_norm(raw_type).lower())
        if mapped:
            sec, typ, legacy_subtype = mapped

    if typ is None:
        for _candidate in (raw_sector, raw_type):
            sector_alias = LEGACY_OBJECT_ALIASES.get(_norm(_candidate).upper())
            if sector_alias and sector_alias[1]:
                typ, legacy_subtype = sector_alias[1], sector_alias[2]
                break

    if typ:
        owner = sector_of_object_type(typ)
        if owner:
            sec = owner

    sub = canonical_object_subtype(raw_subtype, typ)
    if sub is None:
        sub = legacy_subtype
    if sub is None:
        mapped_sub = LEGACY_RUSSIAN_OBJECT_TYPES.get(_norm(raw_subtype).lower())
        if mapped_sub:
            sub = mapped_sub[2]

    return {
        OBJECT_SECTOR_FIELD: sec,
        OBJECT_TYPE_FIELD: typ,
        OBJECT_SUBTYPE_FIELD: sub,
    }


def object_axes_not_applicable(form: Any) -> bool:
    """True when the procurement form has no object lifecycle (direct supply)."""
    f = _norm(form).upper()
    return f in {"DIRECT_GOODS_PURCHASE", "DIRECT_SUPPLY", "SUPPLY", "GOODS"}


def object_axes_for_direct_supply() -> dict[str, str]:
    """Direct goods purchase: object axes are explicitly not applicable."""
    return {
        OBJECT_SECTOR_FIELD: OBJECT_NOT_APPLICABLE,
        OBJECT_TYPE_FIELD: OBJECT_NOT_APPLICABLE,
        OBJECT_SUBTYPE_FIELD: OBJECT_NOT_APPLICABLE,
    }


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
    if sector == OBJECT_NOT_APPLICABLE:
        return "Не применимо (прямая поставка)"
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
        "object_context_terms": len(OBJECT_CONTEXT_TERMS),
        "application_area_terms": len(APPLICATION_AREA_TERMS),
    }


def model_object_hints(assessment: dict | None) -> dict[str, str | None]:
    """Read-only model object hints, normalized to canonical codes.

    Model / free-text output is an input only: it is mapped through
    normalize_object_axes and never auto-accepted into human fields.
    """
    if not assessment:
        return {"sector": None, "object_type": None, "object_subtype": None}
    nr = assessment.get("normalized_result") or {}
    oc = nr.get("object_classification") if isinstance(nr.get("object_classification"), dict) else {}
    axes = normalize_object_axes(
        {
            OBJECT_SECTOR_FIELD: oc.get("object_sector") or nr.get("object_sector"),
            OBJECT_TYPE_FIELD: (
                oc.get("object_type")
                or nr.get("object_type")
                or assessment.get("proposed_object_type")
            ),
            OBJECT_SUBTYPE_FIELD: oc.get("object_subtype") or nr.get("object_subtype"),
        }
    )
    return {
        "sector": axes[OBJECT_SECTOR_FIELD],
        "object_type": axes[OBJECT_TYPE_FIELD],
        "object_subtype": axes[OBJECT_SUBTYPE_FIELD],
    }
