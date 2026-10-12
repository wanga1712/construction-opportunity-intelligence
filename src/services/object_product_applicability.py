"""Canonical OBJECT -> PRODUCT applicability matrix authority (Layer 1).

WIP OBJECT-PRODUCT-CANDIDATE-LAYER-IMPLEMENTATION-V1.

Pipeline position::

    PROCUREMENT_MODE -> CANONICAL OBJECT -> OBJECT x PRODUCT MATRIX -> CANDIDATES

A relation here only says "on this kind of object it makes sense to look for
this product". It is NOT an opportunity and NOT a medal: Layer 1 never scores
Gold/Silver/Bronze, never writes CRM categories and never runs Qwen.

Axis vocabularies are owned elsewhere and are not re-declared as literals here:
  * OBJECT_SECTOR / OBJECT_TYPE / OBJECT_SUBTYPE -> expert_object_taxonomy;
  * PRODUCT_* axes -> product_ontology.

The registry is an in-module TSV blob: one authority file, no runtime I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.services import expert_object_taxonomy as _OT
from src.services import product_ontology as _PO

CANDIDATE_MODEL_VERSION = "object_product_v1"
CANDIDATE_STATUS_PRE_EVIDENCE = "PRE_EVIDENCE"

MATRIX_AUTHORITY = "src/services/object_product_applicability.py"

RELATION_SOURCE_VALUES = (
    "REVIEWED_DISCOVERY",
    "HISTORICAL_BACKTEST",
    "SEMANTIC_REVIEW",
)

_RELATION_HEADER = (
    "OBJECT_SECTOR",
    "OBJECT_TYPE",
    "OBJECT_SUBTYPE",
    "PRODUCT_FAMILY",
    "PRODUCT_TYPE",
    "APPLICATION",
    "MATERIAL",
    "VARIANT",
    "APPLICABILITY",
    "SOURCE",
    "REASON",
)

_RELATION_TSV = """\
OBJECT_SECTOR	OBJECT_TYPE	OBJECT_SUBTYPE	PRODUCT_FAMILY	PRODUCT_TYPE	APPLICATION	MATERIAL	VARIANT	APPLICABILITY	SOURCE	REASON
COMMERCIAL	OFFICE		BARRIER_RAILING	RAILING	TERRITORY			CONDITIONAL	SEMANTIC_REVIEW	ограждение кровли перилами — реальное изделие
COMMERCIAL	PARKING		DRAINAGE	DRAINAGE_TRAY				YES	REVIEWED_DISCOVERY	1 лоток genuine; 1 FP теплосеть
COMMERCIAL	PARKING		DRAINAGE	DRAINAGE_TRAY		CONCRETE		CONDITIONAL	REVIEWED_DISCOVERY	1 лоток genuine; 1 FP теплосеть
COMMERCIAL	PARKING		LIGHTING	LIGHTING_FIXTURE	PARKING			YES	REVIEWED_DISCOVERY	освещение парковки подтверждено по существу
COMMERCIAL	PARKING		LIGHTING	LIGHTING_POLE		METAL		UNKNOWN	REVIEWED_DISCOVERY	0 подтверждающих
INDUSTRIAL	ENERGY_FACILITY		LIGHTING	LIGHTING_FIXTURE	INDUSTRIAL			CONDITIONAL	REVIEWED_DISCOVERY	ТЭЦ охранное освещение есть; FP энергосбережение
INDUSTRIAL	FACTORY		GRATING_AND_DECKING	GRATING	INDUSTRIAL			CONDITIONAL	SEMANTIC_REVIEW	вентиляционная решётка, другое изделие / грязеприёмная/зумпфовая решётка — решётчатое изделие
INDUSTRIAL	PRODUCTION_BUILDING		LIGHTING	LIGHTING_FIXTURE	INDUSTRIAL			UNKNOWN	SEMANTIC_REVIEW	наружный прожектор объекта — единичный случай, применимость не подтверждена / внутреннее освещение здания, не объектное (инфраструктурное) освещение
INFRASTRUCTURE	AIRPORT		LIGHTING	LIGHTING_FIXTURE	TERRITORY			UNKNOWN	SEMANTIC_REVIEW	наружный прожектор объекта — единичный случай, применимость не подтверждена
INFRASTRUCTURE	BRIDGE		DRAINAGE	DRAINAGE_TRAY				CONDITIONAL	REVIEWED_DISCOVERY	0 подтверждающих
INFRASTRUCTURE	BRIDGE		DRAINAGE	DRAINAGE_TRAY		COMPOSITE		UNKNOWN	REVIEWED_DISCOVERY	0 подтверждающих
INFRASTRUCTURE	BRIDGE		LIGHTING	LIGHTING_POLE		METAL		CONDITIONAL	REVIEWED_DISCOVERY	праздничное оформление на мостах, не опора освещения
INFRASTRUCTURE	BRIDGE		LIGHTING	LIGHTING_POLE_BASE_PROTECTOR		COMPOSITE		UNKNOWN	REVIEWED_DISCOVERY	0 подтверждающих
INFRASTRUCTURE	BRIDGE		PIPES	PIPE	BRIDGE			CONDITIONAL	SEMANTIC_REVIEW	труба как конструктивный элемент/изделие, не трубная продукция / водопропускная труба — искусственное сооружение объекта / описан способ работ/компонент, не продукт PIPE
INFRASTRUCTURE	BRIDGE		BARRIER_RAILING	RAILING		COMPOSITE		YES	REVIEWED_DISCOVERY	перильное/парапетное ограждение мостов
INFRASTRUCTURE	BRIDGE		BARRIER_RAILING	RAILING		METAL		YES	REVIEWED_DISCOVERY	перильное/парапетное ограждение мостов
INFRASTRUCTURE	BRIDGE		BARRIER_RAILING	ROAD_BARRIER		METAL		YES	REVIEWED_DISCOVERY	мостовое барьерное; 1 стройконтроль
INFRASTRUCTURE	MUNICIPAL_INFRASTRUCTURE		DRAINAGE	DRAINAGE_PUMP				YES	REVIEWED_DISCOVERY	дренажные насосные станции (ДНС)
INFRASTRUCTURE	MUNICIPAL_INFRASTRUCTURE		DRAINAGE	DRAINAGE_TRAY	UTILITY_NETWORK			YES	SEMANTIC_REVIEW	водоотводный лоток — профильный продукт объекта
INFRASTRUCTURE	MUNICIPAL_INFRASTRUCTURE		GRATING_AND_DECKING	GRATING	UTILITY_NETWORK			CONDITIONAL	SEMANTIC_REVIEW	решётка ливнеприёмного лотка — решётчатое изделие
INFRASTRUCTURE	MUNICIPAL_INFRASTRUCTURE		DRAINAGE	STORM_WATER_INLET	UTILITY_NETWORK			YES	SEMANTIC_REVIEW	дождеприёмник — профильный продукт объекта / решётка дождеприёмника — изделие системы
INFRASTRUCTURE	RAILWAY		GRATING_AND_DECKING	GRATING	TERRITORY			CONDITIONAL	SEMANTIC_REVIEW	резино-кордовый настил ж/д переезда (decking)
INFRASTRUCTURE	RAILWAY		PIPES	PIPE	TERRITORY			CONDITIONAL	SEMANTIC_REVIEW	водопропускная труба — искусственное сооружение объекта
INFRASTRUCTURE	ROAD		DRAINAGE	DRAINAGE_TRAY				YES	REVIEWED_DISCOVERY	композитора Касьянова / цвет ограждения
INFRASTRUCTURE	ROAD		DRAINAGE	DRAINAGE_TRAY		CONCRETE		YES	REVIEWED_DISCOVERY	композитора Касьянова / цвет ограждения
INFRASTRUCTURE	ROAD		LIGHTING	LIGHTING_BRACKET		METAL		YES	REVIEWED_DISCOVERY	кронштейны на линии электроосвещения
INFRASTRUCTURE	ROAD		LIGHTING	LIGHTING_FIXTURE				YES	REVIEWED_DISCOVERY	примеры = освещение автодорог
INFRASTRUCTURE	ROAD		LIGHTING	LIGHTING_FIXTURE	ROAD			YES	REVIEWED_DISCOVERY	примеры = освещение автодорог
INFRASTRUCTURE	ROAD		LIGHTING	LIGHTING_POLE		METAL		CONDITIONAL	REVIEWED_DISCOVERY	1 ЛЭП FP; слабый evidence
INFRASTRUCTURE	ROAD		PIPES	PIPE	ROAD			CONDITIONAL	SEMANTIC_REVIEW	водопропускная труба — искусственное сооружение объекта / контекст не позволяет отнести трубу к объектному продукту / нормативная ссылка/классификация, не закупочный продукт / дренаж/ливневка в объект
INFRASTRUCTURE	ROAD		BARRIER_RAILING	RAILING		COMPOSITE		CONDITIONAL	REVIEWED_DISCOVERY	пешеходные ограждения вдоль дорог - массово
INFRASTRUCTURE	ROAD		BARRIER_RAILING	RAILING		METAL		YES	REVIEWED_DISCOVERY	пешеходные ограждения вдоль дорог - массово
INFRASTRUCTURE	ROAD		BARRIER_RAILING	ROAD_BARRIER		METAL		YES	REVIEWED_DISCOVERY	барьерные ограждения дорог
INFRASTRUCTURE	ROAD		DRAINAGE	STORM_WATER_INLET				YES	REVIEWED_DISCOVERY	дождеприемники дорог
INFRASTRUCTURE	STREET		DRAINAGE	DRAINAGE_TRAY				YES	REVIEWED_DISCOVERY	композиторов -> композит; не лоток
INFRASTRUCTURE	STREET		DRAINAGE	DRAINAGE_TRAY		CONCRETE		YES	REVIEWED_DISCOVERY	композиторов -> композит; не лоток
INFRASTRUCTURE	STREET		LIGHTING	LIGHTING_BRACKET		METAL		YES	REVIEWED_DISCOVERY	кронштейны уличных светильников
INFRASTRUCTURE	STREET		LIGHTING	LIGHTING_FIXTURE				YES	REVIEWED_DISCOVERY	2 FP: адресная подстрока улица в др.объектах
INFRASTRUCTURE	STREET		LIGHTING	LIGHTING_FIXTURE	STREET			YES	REVIEWED_DISCOVERY	2 FP: адресная подстрока улица в др.объектах
INFRASTRUCTURE	STREET		LIGHTING	LIGHTING_POLE		METAL		CONDITIONAL	REVIEWED_DISCOVERY	опоры как место крепления (флаги/декор), не покупаемое изделие
INFRASTRUCTURE	STREET		PIPES	PIPE	STREET			CONDITIONAL	SEMANTIC_REVIEW	дренаж/ливневка в объектном контексте
INFRASTRUCTURE	STREET		BARRIER_RAILING	RAILING		COMPOSITE		CONDITIONAL	REVIEWED_DISCOVERY	пешеходные ограждения тротуаров
INFRASTRUCTURE	STREET		BARRIER_RAILING	RAILING		METAL		YES	REVIEWED_DISCOVERY	пешеходные ограждения тротуаров
INFRASTRUCTURE	STREET		BARRIER_RAILING	ROAD_BARRIER		METAL		YES	REVIEWED_DISCOVERY	барьерные ограждения улиц/тротуаров
INFRASTRUCTURE	STREET		BARRIER_RAILING	TERRITORY_FENCE		METAL		CONDITIONAL	REVIEWED_DISCOVERY	FP: забор в закупках водопровода/котельной
INFRASTRUCTURE	TUNNEL		LIGHTING	LIGHTING_FIXTURE	TUNNEL			YES	REVIEWED_DISCOVERY	тоннельные светильники есть; FP просвещения->освещение
INFRASTRUCTURE	TUNNEL		LIGHTING	LIGHTING_POLE		METAL		NO	REVIEWED_DISCOVERY	в тоннеле опоры конструктивно не применяются
INFRASTRUCTURE	TUNNEL		BARRIER_RAILING	RAILING		COMPOSITE		UNKNOWN	REVIEWED_DISCOVERY	0 подтверждающих
INFRASTRUCTURE	TUNNEL		BARRIER_RAILING	ROAD_BARRIER		METAL		UNKNOWN	REVIEWED_DISCOVERY	0 подтверждающих
INFRASTRUCTURE	UTILITY_NETWORKS		DRAINAGE	DRAINAGE_TRAY				CONDITIONAL	REVIEWED_DISCOVERY	ливневая канализация = сеть, не лоток
INFRASTRUCTURE	UTILITY_NETWORKS		LIGHTING	LIGHTING_FIXTURE				CONDITIONAL	REVIEWED_DISCOVERY	FP: театр Вл.Маяковского, школа вл.; Электросеть genuine
INFRASTRUCTURE	UTILITY_NETWORKS		PIPES	PIPE		COMPOSITE		YES	REVIEWED_DISCOVERY	387970 стеклопластиковый трубопровод
INFRASTRUCTURE	UTILITY_NETWORKS		DRAINAGE	STORM_WATER_INLET				YES	REVIEWED_DISCOVERY	дождеприемники ливневки
RESIDENTIAL	APARTMENT_BUILDING		LIGHTING	LIGHTING_POLE	TERRITORY			CONDITIONAL	SEMANTIC_REVIEW	опоры наружного освещения в объектном контексте
SOCIAL	KINDERGARTEN		DRAINAGE	DRAINAGE_TRAY	TERRITORY			CONDITIONAL	SEMANTIC_REVIEW	водоотводный лоток в объектном контексте
SOCIAL	SCHOOL		BARRIER_RAILING	TERRITORY_FENCE		METAL		YES	REVIEWED_DISCOVERY	ограждение территории (забор) - renamе к TERRITORY_FENCE
SOCIAL	SOCIAL_CARE		LIGHTING	LIGHTING_FIXTURE	TERRITORY			UNKNOWN	SEMANTIC_REVIEW	наружный прожектор объекта — единичный случай, применимость не подтверждена
SOCIAL	SPORTS_FACILITY		BARRIER_RAILING	TERRITORY_FENCE	TERRITORY			CONDITIONAL	SEMANTIC_REVIEW	периметральное ограждение территории
SOCIAL	UNIVERSITY		DRAINAGE	DRAINAGE_PUMP	TERRITORY			CONDITIONAL	SEMANTIC_REVIEW	дренажный насос в приямке объекта / дренажный насос как комплект кондиционера
SOCIAL	UNIVERSITY		LIGHTING	LIGHTING_POLE	TERRITORY			UNKNOWN	SEMANTIC_REVIEW	единичное каталожное упоминание опоры освещения
URBAN_IMPROVEMENT	COURTYARD		DRAINAGE	DRAINAGE_TRAY		CONCRETE		YES	REVIEWED_DISCOVERY	лотки на дворовых территориях
URBAN_IMPROVEMENT	COURTYARD		LIGHTING	LIGHTING_FIXTURE	OTHER_URBAN			YES	REVIEWED_DISCOVERY	наружное освещение дворовых проездов
URBAN_IMPROVEMENT	COURTYARD		LIGHTING	LIGHTING_POLE	COURTYARD			CONDITIONAL	SEMANTIC_REVIEW	опоры наружного освещения в объектном контексте
URBAN_IMPROVEMENT	COURTYARD		PIPES	PIPE	COURTYARD			CONDITIONAL	SEMANTIC_REVIEW	внутренняя инженерная система здания, не объектный продукт / дренаж/ливневка в объектном контексте
URBAN_IMPROVEMENT	COURTYARD		BARRIER_RAILING	RAILING		METAL		YES	REVIEWED_DISCOVERY	ограждения дворовых территорий
URBAN_IMPROVEMENT	EMBANKMENT		LIGHTING	LIGHTING_FIXTURE	OTHER_URBAN			YES	REVIEWED_DISCOVERY	FP: город Набережные Челны
URBAN_IMPROVEMENT	EMBANKMENT		PIPES	PIPE	EMBANKMENT			UNKNOWN	SEMANTIC_REVIEW	труба как конструктивный элемент/изделие, не трубная продукция / контекст не позволяет отнести трубу к объектному продукту / внутренняя инженерная система здания, не объектный продукт
URBAN_IMPROVEMENT	PARK		DRAINAGE	DRAINAGE_TRAY		CONCRETE		CONDITIONAL	REVIEWED_DISCOVERY	лотки в парке/сквере; часть ливневка
URBAN_IMPROVEMENT	PARK		LIGHTING	LIGHTING_FIXTURE	PARK			YES	REVIEWED_DISCOVERY	парковое освещение подтверждено
URBAN_IMPROVEMENT	PARK		LIGHTING	LIGHTING_POLE		METAL		CONDITIONAL	REVIEWED_DISCOVERY	FP: промышленный парк; 1 реальный парк
URBAN_IMPROVEMENT	PARK		BARRIER_RAILING	ROAD_BARRIER		METAL		NO	REVIEWED_DISCOVERY	конструктивно не типовое решение
URBAN_IMPROVEMENT	PEDESTRIAN_ZONE		DRAINAGE	DRAINAGE_TRAY		CONCRETE		YES	REVIEWED_DISCOVERY	лотки на пешеходной зоне
URBAN_IMPROVEMENT	PEDESTRIAN_ZONE		GRATING_AND_DECKING	GRATING	PEDESTRIAN_ZONE			CONDITIONAL	SEMANTIC_REVIEW	полимерная решётка в объектном контексте
URBAN_IMPROVEMENT	PEDESTRIAN_ZONE		BARRIER_RAILING	RAILING		COMPOSITE		YES	REVIEWED_DISCOVERY	262346 композитные пешеходные ограждения
URBAN_IMPROVEMENT	PLAYGROUND		LIGHTING	LIGHTING_FIXTURE	OTHER_URBAN			YES	REVIEWED_DISCOVERY	освещение детских площадок
URBAN_IMPROVEMENT	PLAYGROUND		BARRIER_RAILING	RAILING		METAL		YES	REVIEWED_DISCOVERY	ограждения площадок
URBAN_IMPROVEMENT	PUBLIC_SPACE		DRAINAGE	DRAINAGE_TRAY	OTHER_URBAN			CONDITIONAL	SEMANTIC_REVIEW	водоотводный лоток в объектном контексте
URBAN_IMPROVEMENT	SQUARE		LIGHTING	LIGHTING_FIXTURE	PARK			YES	REVIEWED_DISCOVERY	освещение скверов подтверждено"""


def _norm(value: Any) -> str:
    """Upper-case trimmed code; None/blank becomes an empty string."""
    if value is None:
        return ""
    return str(value).strip().upper()


@dataclass(frozen=True, slots=True)
class ObjectProductRelation:
    """One reviewed OBJECT x PRODUCT applicability relation."""

    object_sector: str
    object_type: str
    object_subtype: str | None
    product_family: str
    product_type: str
    application: str | None
    material: str | None
    variant: str | None
    applicability: str
    source: str
    reason: str

    @property
    def is_candidate(self) -> bool:
        """YES and CONDITIONAL produce candidates; UNKNOWN/NO do not."""
        return self.applicability in (
            _PO.APPLICABILITY_YES,
            _PO.APPLICABILITY_CONDITIONAL,
        )

    def product_axes(self) -> tuple[str | None, ...]:
        return (
            self.product_family,
            self.product_type,
            self.application,
            self.material,
            self.variant,
        )

    def key(self) -> tuple[str, ...]:
        """Deduplication key: object axes + canonical product axes."""
        return (
            self.object_sector,
            self.object_type,
            self.object_subtype or "",
        ) + tuple(x or "" for x in self.product_axes())

    def as_dict(self) -> dict[str, Any]:
        return {
            "OBJECT_SECTOR": self.object_sector,
            "OBJECT_TYPE": self.object_type,
            "OBJECT_SUBTYPE": self.object_subtype,
            "PRODUCT_FAMILY": self.product_family,
            "PRODUCT_TYPE": self.product_type,
            "APPLICATION": self.application,
            "MATERIAL": self.material,
            "VARIANT": self.variant,
            "APPLICABILITY": self.applicability,
            "SOURCE": self.source,
            "REASON": self.reason,
        }


def _parse_relations(text: str) -> tuple[ObjectProductRelation, ...]:
    rows: list[ObjectProductRelation] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if tuple(parts[: len(_RELATION_HEADER)]) == _RELATION_HEADER:
            continue
        if len(parts) < len(_RELATION_HEADER):
            parts = parts + [""] * (len(_RELATION_HEADER) - len(parts))
        rows.append(
            ObjectProductRelation(
                object_sector=_norm(parts[0]),
                object_type=_norm(parts[1]),
                object_subtype=_norm(parts[2]) or None,
                product_family=_norm(parts[3]),
                product_type=_norm(parts[4]),
                application=_norm(parts[5]) or None,
                material=_norm(parts[6]) or None,
                variant=_norm(parts[7]) or None,
                applicability=_norm(parts[8]),
                source=_norm(parts[9]),
                reason=parts[10].strip(),
            )
        )
    return tuple(rows)


RELATIONS: tuple[ObjectProductRelation, ...] = _parse_relations(_RELATION_TSV)


def relations() -> tuple[ObjectProductRelation, ...]:
    """The frozen canonical registry (never mutated at runtime)."""
    return RELATIONS


def matrix_stats() -> dict[str, Any]:
    """Counts for reporting; distinct relations, not evidence rows."""
    by_applicability: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_family: dict[str, int] = {}
    objects: set[tuple[str, str, str]] = set()
    for rel in RELATIONS:
        by_applicability[rel.applicability] = by_applicability.get(rel.applicability, 0) + 1
        by_source[rel.source] = by_source.get(rel.source, 0) + 1
        by_family[rel.product_family] = by_family.get(rel.product_family, 0) + 1
        objects.add((rel.object_sector, rel.object_type, rel.object_subtype or ""))
    return {
        "relations": len(RELATIONS),
        "distinct_objects": len(objects),
        "by_applicability": by_applicability,
        "by_source": by_source,
        "by_product_family": by_family,
    }


def validate_matrix() -> tuple[str, ...]:
    """Return human-readable problems; empty tuple means the matrix is valid."""
    problems: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for rel in RELATIONS:
        tag = f"{rel.object_type}/{rel.product_type}"
        if rel.applicability not in _PO.APPLICABILITY_VALUES:
            problems.append(f"{tag}: invalid APPLICABILITY {rel.applicability!r}")
        if rel.source not in RELATION_SOURCE_VALUES:
            problems.append(f"{tag}: invalid SOURCE {rel.source!r}")
        if not _OT.is_canonical_object_type(rel.object_type, rel.object_sector):
            problems.append(f"{tag}: object axes are not canonical")
        elif rel.object_subtype and not _OT.is_canonical_object_subtype(
            rel.object_subtype, rel.object_type
        ):
            problems.append(f"{tag}: invalid OBJECT_SUBTYPE {rel.object_subtype!r}")
        for problem in _PO.validate_product_axes(
            family=rel.product_family,
            product_type=rel.product_type,
            application=rel.application,
            material=rel.material,
            variant=rel.variant,
        ):
            problems.append(f"{tag}: {problem}")
        if not rel.reason:
            problems.append(f"{tag}: missing REASON")
        key = rel.key()
        if key in seen:
            problems.append(f"{tag}: duplicate relation for axes {key}")
        seen.add(key)
    return tuple(problems)


def applicability_for(
    *,
    object_sector: Any,
    object_type: Any,
    object_subtype: Any = None,
    product_family: Any,
    product_type: Any,
    application: Any = None,
    material: Any = None,
    variant: Any = None,
) -> str | None:
    """Look up the reviewed applicability for exact axes, or None if absent."""
    wanted = (
        _norm(object_sector),
        _norm(object_type),
        _norm(object_subtype),
        _norm(product_family),
        _norm(product_type),
        _norm(application),
        _norm(material),
        _norm(variant),
    )
    for rel in RELATIONS:
        if rel.key() == wanted:
            return rel.applicability
    return None


def candidate_generation_enabled(procurement_mode: Any) -> bool:
    """Gate 0: only OBJECT procurement generates embedded product candidates."""
    mode = _norm(procurement_mode)
    if mode not in _PO.PROCUREMENT_MODE_VALUES:
        return False
    if not _PO.product_candidate_generation_allowed(mode):
        return False
    return mode == _PO.PROCUREMENT_MODE_OBJECT


def resolve_object(
    object_sector: Any = None,
    object_type: Any = None,
    object_subtype: Any = None,
) -> tuple[str, str, str | None] | None:
    """Canonical object axes or None. No classification: canonical codes only.

    Free text and legacy aliases return None; the object layer resolves them
    upstream, the generator never guesses.
    """
    code = _norm(object_type)
    if not _OT.is_canonical_object_type(code):
        return None
    owner = _OT.sector_of_object_type(code)
    sector = _norm(object_sector) or owner
    if not owner or sector != owner:
        return None
    subtype = _norm(object_subtype) or None
    if subtype and not _OT.is_canonical_object_subtype(subtype, code):
        return None
    return sector, code, subtype


def _matching_relations(object_axes: tuple[str, str, str | None]) -> list[ObjectProductRelation]:
    sector, object_type, subtype = object_axes
    matched = []
    for rel in RELATIONS:
        if rel.object_sector != sector or rel.object_type != object_type:
            continue
        if rel.object_subtype and rel.object_subtype != subtype:
            continue
        matched.append(rel)
    return matched


def generate_candidates(
    procurement_mode: Any = None,
    *,
    object_sector: Any = None,
    object_type: Any = None,
    object_subtype: Any = None,
    object_context: Any = None,
    crm_id: Any = None,
    include_unknown: bool = False,
    model_version: str = CANDIDATE_MODEL_VERSION,
) -> list[dict[str, Any]]:
    """Layer 1: OBJECT -> PRE_EVIDENCE product candidates (never medals).

    Gates: mode must be OBJECT (DIRECT / SERVICE_NO_OBJECT / AMBIGUOUS -> none);
    object must resolve to canonical axes; NO is skipped, UNKNOWN is skipped
    unless ``include_unknown`` (then it is a diagnostic row, not a candidate).
    """
    if not candidate_generation_enabled(procurement_mode):
        return []
    object_axes = resolve_object(object_sector, object_type, object_subtype)
    if object_axes is None:
        return []
    sector, resolved_type, resolved_subtype = object_axes
    mode = _norm(procurement_mode)

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str | None, ...]] = set()
    for rel in _matching_relations(object_axes):
        if rel.applicability == _PO.APPLICABILITY_NO:
            continue
        if rel.applicability == _PO.APPLICABILITY_UNKNOWN and not include_unknown:
            continue
        key = rel.product_axes()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "CRM_ID": crm_id,
                "PROCUREMENT_MODE": mode,
                "OBJECT_SECTOR": sector,
                "OBJECT_TYPE": resolved_type,
                "OBJECT_SUBTYPE": resolved_subtype,
                "OBJECT_CONTEXT": object_context,
                "PRODUCT_FAMILY": rel.product_family,
                "PRODUCT_TYPE": rel.product_type,
                "APPLICATION": rel.application,
                "MATERIAL": rel.material,
                "VARIANT": rel.variant,
                "APPLICABILITY": rel.applicability,
                "SOURCE": rel.source,
                "REASON": rel.reason,
                "CANDIDATE_STATUS": CANDIDATE_STATUS_PRE_EVIDENCE,
                "CANDIDATE_MODEL_VERSION": model_version,
            }
        )
    candidates.sort(
        key=lambda c: (
            c["PRODUCT_FAMILY"] or "",
            c["PRODUCT_TYPE"] or "",
            c["APPLICATION"] or "",
            c["MATERIAL"] or "",
            c["VARIANT"] or "",
        )
    )
    return candidates


def unresolved_relations() -> tuple[ObjectProductRelation, ...]:
    """Diagnostic view: relations still stored as UNKNOWN."""
    return tuple(r for r in RELATIONS if r.applicability == _PO.APPLICABILITY_UNKNOWN)


def user_projection(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a human label to each candidate without creating a product type."""
    projected = []
    for candidate in candidates:
        row = dict(candidate)
        row["USER_LABEL"] = _PO.user_facing_label(
            product_type=candidate.get("PRODUCT_TYPE"),
            application=candidate.get("APPLICATION"),
            material=candidate.get("MATERIAL"),
            variant=candidate.get("VARIANT"),
        )
        projected.append(row)
    return projected
