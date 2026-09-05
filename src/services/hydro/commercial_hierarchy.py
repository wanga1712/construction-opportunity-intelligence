"""Deterministic Hydro commercial hierarchy and Qwen shadow contracts.

Facts are classified from the canonical snapshot. Qwen receives a derived
commercial context only; it never creates or mutates factual fields.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable


class CommercialLayer(StrEnum):
    ZHILISHNIK = "ZHILISHNIK"
    OTHER_UK = "OTHER_UK"
    NO_UK_KNOWN = "NO_UK_KNOWN"
    UNKNOWN = "UNKNOWN"


class ManagementContour(StrEnum):
    ZHILISHNIK = "ZHILISHNIK"
    OTHER_UK = "OTHER_UK"
    UNRESOLVED = "UNRESOLVED"


class HydroObjectCommercialClass(StrEnum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL_RETAIL = "COMMERCIAL_RETAIL"
    COMMERCIAL_OFFICE = "COMMERCIAL_OFFICE"
    HOTEL = "HOTEL"
    INDUSTRIAL = "INDUSTRIAL"
    STATE_PUBLIC = "STATE_PUBLIC"
    SOCIAL = "SOCIAL"
    SPORT = "SPORT"
    CULTURAL = "CULTURAL"
    TRANSPORT = "TRANSPORT"
    OTHER_KNOWN = "OTHER_KNOWN"
    UNKNOWN = "UNKNOWN"


class QwenChannel(StrEnum):
    MANAGEMENT_COMPANY = "MANAGEMENT_COMPANY"
    ZHILISHNIK = "ZHILISHNIK"
    OWNER_OPERATOR = "OWNER_OPERATOR"
    FACILITY_MANAGEMENT = "FACILITY_MANAGEMENT"
    PUBLIC_PROCUREMENT = "PUBLIC_PROCUREMENT"
    BALANCE_HOLDER = "BALANCE_HOLDER"
    DEVELOPER = "DEVELOPER"
    RESEARCH_REQUIRED = "RESEARCH_REQUIRED"


PROMPT_VERSION = "hydro_commercial_interest_v1"
ASSESSMENT_VERSION = "hydro_commercial_interest_v1"


@dataclass(frozen=True)
class ManagementFacts:
    management_company_id: int | str | None = None
    source_company_id: str | None = None
    name: str | None = None
    inn: str | None = None
    ogrn: str | None = None


@dataclass(frozen=True)
class ObjectCommercialClass:
    commercial_class: HydroObjectCommercialClass
    confidence: float
    reasons: tuple[str, ...] = ()
    missing_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortfolioScore:
    score: int
    grade: str
    reasons: tuple[str, ...] = ()
    missing_signals: tuple[str, ...] = ()
    version: str = "hydro_company_portfolio_v1"


@dataclass(frozen=True)
class CommercialEntity:
    layer: CommercialLayer
    entity_key: str
    management: ManagementFacts | None
    objects: tuple[dict[str, Any], ...]
    object_class: ObjectCommercialClass | None = None
    portfolio_score: PortfolioScore | None = None


def _text(*values: Any) -> str:
    return " ".join(str(value).strip().lower() for value in values if value not in (None, ""))


def normalized_name(value: str | None) -> str:
    return re.sub(r"[^a-zа-я0-9]+", " ", (value or "").lower()).strip()


def classify_management_contour(facts: ManagementFacts) -> ManagementContour:
    """Classify a resolved company without merging legal identities.

    The exact company identity is retained by ID/INN/OGRN. The name is used
    only to assign a contour, never as a grouping key.
    """
    if facts.management_company_id is None and not any((facts.inn, facts.ogrn, facts.source_company_id)):
        return ManagementContour.UNRESOLVED
    if "жилищник" in normalized_name(facts.name):
        return ManagementContour.ZHILISHNIK
    return ManagementContour.OTHER_UK


_CLASS_RULES: tuple[tuple[HydroObjectCommercialClass, tuple[str, ...], str], ...] = (
    (HydroObjectCommercialClass.CULTURAL, ("музей", "театр", "культур", "выставоч", "дворец"), "cultural signal"),
    (HydroObjectCommercialClass.STATE_PUBLIC, ("кремл", "государств", "администрац", "министер", "правитель", "ведомств", "муницип", "суд", "спец", "оборон"), "state/public signal"),
    (HydroObjectCommercialClass.SOCIAL, ("школ", "детск", "больниц", "поликлин", "образователь", "медицин", "социальн"), "social signal"),
    (HydroObjectCommercialClass.SPORT, ("стадион", "спортив", "бассейн", "фитнес"), "sport signal"),
    (HydroObjectCommercialClass.TRANSPORT, ("вокзал", "аэропорт", "метро", "транспорт"), "transport signal"),
    (HydroObjectCommercialClass.HOTEL, ("гостиниц", "отел", "hotel"), "hotel signal"),
    (HydroObjectCommercialClass.COMMERCIAL_RETAIL, ("торгов", "магазин", "ритейл", "shopping"), "retail signal"),
    (HydroObjectCommercialClass.COMMERCIAL_OFFICE, ("офис", "административ", "деловой", "бизнес"), "office signal"),
    (HydroObjectCommercialClass.INDUSTRIAL, ("производ", "завод", "промышлен", "склад"), "industrial signal"),
    (HydroObjectCommercialClass.RESIDENTIAL, ("жил", "многоквартир", "жк "), "residential signal"),
)


def classify_object(row: dict[str, Any]) -> ObjectCommercialClass:
    """Classify no-UK objects from purpose/type/name, never from address alone."""
    purpose = row.get("purpose")
    object_type = row.get("object_type")
    name = row.get("name") or (row.get("source_payload") or {}).get("name")
    text = _text(purpose, object_type, name)
    missing = tuple(label for value, label in ((purpose, "purpose"), (object_type, "object_type"), (name, "name")) if not value)
    if not text:
        return ObjectCommercialClass(HydroObjectCommercialClass.UNKNOWN, 0.0, (), missing)
    for category, signals, reason in _CLASS_RULES:
        if any(signal in text for signal in signals):
            return ObjectCommercialClass(category, 0.9 if purpose or object_type else 0.7, (reason,), missing)
    return ObjectCommercialClass(HydroObjectCommercialClass.OTHER_KNOWN, 0.55, ("canonical facts present",), missing)


def _grade(score: int) -> str:
    return "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 35 else "D"


def company_portfolio_score(objects: Iterable[dict[str, Any]]) -> PortfolioScore:
    rows = list(objects)
    potentials = [int((row.get("object_potential") or {}).get("score", 0)) for row in rows]
    strong = sum(score >= 70 for score in potentials)
    ge2 = sum((row.get("floors_underground") or 0) >= 2 for row in rows)
    known_area = sum(float(row["area_total"]) for row in rows if row.get("area_total") is not None)
    best = max(potentials, default=0)
    score = min(100, round(min(strong, 10) * 4 + min(ge2, 8) * 3 + min(known_area / 10000, 20) + best * 0.35))
    reasons = tuple(x for x, present in ((f"{strong} strong objects", strong > 0), (f"{ge2} objects with >=2 underground floors", ge2 > 0), ("known area", known_area > 0)) if present)
    missing = ("portfolio area",) if not known_area else ()
    return PortfolioScore(score, _grade(score), reasons, missing)


def build_commercial_entities(rows: Iterable[dict[str, Any]]) -> tuple[CommercialEntity, ...]:
    """Group resolved objects by exact company identity; classify unresolved individually."""
    resolved: dict[str, list[dict[str, Any]]] = {}
    unresolved: list[dict[str, Any]] = []
    for row in rows:
        company_id = row.get("management_company_id")
        if company_id is None:
            unresolved.append(row)
        else:
            resolved.setdefault(str(company_id), []).append(row)
    entities: list[CommercialEntity] = []
    for key, objects in resolved.items():
        first = objects[0]
        facts = ManagementFacts(key, first.get("source_company_id"), first.get("company_name"), first.get("company_inn"), first.get("company_ogrn"))
        contour = classify_management_contour(facts)
        entities.append(CommercialEntity(CommercialLayer.ZHILISHNIK if contour == ManagementContour.ZHILISHNIK else CommercialLayer.OTHER_UK, f"hydro:company:{key}", facts, tuple(objects), portfolio_score=company_portfolio_score(objects)))
    for row in unresolved:
        classification = classify_object(row)
        layer = CommercialLayer.UNKNOWN if classification.commercial_class == HydroObjectCommercialClass.UNKNOWN else CommercialLayer.NO_UK_KNOWN
        entities.append(CommercialEntity(layer, f"hydro:object:{row.get('object_id', row.get('source_object_id'))}", None, (row,), classification))
    return tuple(entities)


def shadow_input_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _score_value(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    try:
        return int(value.get("score")) if value.get("score") is not None else None
    except (TypeError, ValueError):
        return None


def _commercial_object_summary(row: dict[str, Any], *, include_address: bool) -> dict[str, Any]:
    """Minimize canonical facts before they reach any assessment provider."""
    potential = row.get("object_potential") if isinstance(row.get("object_potential"), dict) else {}
    readiness = row.get("lead_readiness") if isinstance(row.get("lead_readiness"), dict) else {}
    summary = {
        "purpose": row.get("purpose"),
        "object_type": row.get("object_type"),
        "commercial_name": row.get("name"),
        "area_total": row.get("area_total"),
        "floors_underground": row.get("floors_underground"),
        "floors_total": row.get("floors_total"),
        "construction_finish_year": row.get("construction_finish_year"),
        "commissioning_year": row.get("commissioning_year"),
        "parking_type": row.get("parking_type"),
        "technical_potential": potential,
        "lead_readiness": readiness,
    }
    if include_address:
        summary["address"] = row.get("address")
    return {key: value for key, value in summary.items() if value not in (None, "", {})}


def build_commercial_assessment_payload(entity: CommercialEntity) -> dict[str, Any]:
    """Build a minimized verified/derived payload for any commercial provider."""
    if entity.management:
        objects = [_commercial_object_summary(row, include_address=False) for row in entity.objects]
        potential_scores = [_score_value(row.get("object_potential")) for row in entity.objects]
        purposes = sorted({str(row.get("purpose")) for row in entity.objects if row.get("purpose")})
        object_types = sorted({str(row.get("object_type")) for row in entity.objects if row.get("object_type")})
        phone_available = any(bool(row.get("company_phone_exists")) for row in entity.objects)
        facts = {
            "entity_type": "COMPANY_PORTFOLIO",
            "organization": {"name": entity.management.name, "contour": entity.layer.value, "inn": entity.management.inn, "ogrn": entity.management.ogrn, "phone_available": phone_available},
            "portfolio": {
                "object_count": len(entity.objects),
                "strong_object_count": sum(1 for score in potential_scores if score is not None and score >= 70),
                "underground_2plus_count": sum(1 for row in entity.objects if (row.get("floors_underground") or 0) >= 2),
                "known_area_total": sum(float(row.get("area_total") or 0) for row in entity.objects),
                "purpose_distribution": purposes,
                "object_type_distribution": object_types,
                "top_objects": sorted(objects, key=lambda row: _score_value(row.get("technical_potential")) or 0, reverse=True)[:10],
            },
            "missing": list(entity.portfolio_score.missing_signals if entity.portfolio_score else ()),
        }
    else:
        row = entity.objects[0]
        facts = {"entity_type": "OBJECT", "commercial_class": entity.object_class.commercial_class.value if entity.object_class else "UNKNOWN", "object": _commercial_object_summary(row, include_address=True), "missing": list(entity.object_class.missing_signals if entity.object_class else ())}
    return {"contract": PROMPT_VERSION, "facts": facts, "instruction": "Separate FACT, INFERENCE and MISSING DATA. Do not invent owner, UK, contacts, leaks, procurement or building access."}


def build_qwen_shadow_payload(entity: CommercialEntity) -> dict[str, Any]:
    """Backward-compatible name for the provider-neutral minimized payload."""
    return build_commercial_assessment_payload(entity)


def build_qwen_shadow_prompt(entity: CommercialEntity) -> str:
    payload = build_qwen_shadow_payload(entity)
    return (
        "You are an advisory commercial-interest assessor for Hydro waterproofing. "
        "Return JSON only with exactly the requested output fields. Do not establish facts. "
        "Never invent an owner, management company, contact, leak, problem, procurement mechanism, "
        "or building access. Treat absent data as MISSING DATA, not as evidence of absence. "
        "Separate FACT, INFERENCE and MISSING DATA. This is shadow mode: the result cannot mutate CRM facts.\n\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        + "\nOutput fields: commercial_interest_score integer 0..100; commercial_interest_grade A|B|C|D; "
        "recommended_channel MANAGEMENT_COMPANY|ZHILISHNIK|OWNER_OPERATOR|FACILITY_MANAGEMENT|PUBLIC_PROCUREMENT|"
        "BALANCE_HOLDER|DEVELOPER|RESEARCH_REQUIRED; priority HIGH|MEDIUM|LOW|RESEARCH; reasons string array; "
        "risks string array; next_research_step string; confidence number 0..1."
    )


def validate_shadow_result(result: dict[str, Any]) -> dict[str, Any]:
    allowed = {"commercial_interest_score", "commercial_interest_grade", "recommended_channel", "priority", "reasons", "risks", "next_research_step", "confidence"}
    if set(result) - allowed:
        raise ValueError("unexpected Qwen shadow fields")
    score = result.get("commercial_interest_score")
    if not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("invalid commercial_interest_score")
    if result.get("commercial_interest_grade") not in {"A", "B", "C", "D"}:
        raise ValueError("invalid commercial_interest_grade")
    if result.get("recommended_channel") not in {channel.value for channel in QwenChannel}:
        raise ValueError("invalid recommended_channel")
    if result.get("priority") not in {"HIGH", "MEDIUM", "LOW", "RESEARCH"}:
        raise ValueError("invalid priority")
    confidence = result.get("confidence")
    if not isinstance(confidence, (float, int)) or not 0 <= float(confidence) <= 1:
        raise ValueError("invalid confidence")
    for field_name in ("reasons", "risks"):
        if not isinstance(result.get(field_name), list) or not all(isinstance(item, str) for item in result[field_name]):
            raise ValueError(f"invalid {field_name}")
    return result
