"""Canonical product ontology: PRODUCT_FAMILY / PRODUCT_TYPE / APPLICATION /
MATERIAL / VARIANT / TECHNOLOGY.

WIP=PRODUCT-ONTOLOGY-CANONICAL-IMPLEMENTATION-V1.

This module is the single authority for the product vocabulary. It is a
*semantic* layer kept deliberately separate from the CRM commercial category
registry (``crm_product_categories`` / ``product_subcategory_seed_data`` /
``product_subcategories_service`` / ``commercial_taxonomy_registry``): those keep
user-facing commercial groups («Светотехника»), while this module describes the
concrete product, its object application, material, variant and technology.

Contract
--------
* PRODUCT_FAMILY is a commercial group. ``COMPOSITES`` is *not* a family:
  COMPOSITE is a MATERIAL (see :data:`MATERIAL_VALUES`).
* PRODUCT_TYPE is a standalone product/system; each type belongs to exactly one
  family and impossible family/type pairs are rejected.
* APPLICATION answers *where / on which object* a product is used. Object-typed
  legacy lighting values (``ROAD_LIGHTING`` ...) are APPLICATION, not types.
* MATERIAL is what a product is made of; it is never a PRODUCT_TYPE.
* VARIANT is a constructive execution (``LINEAR`` / ``WELL``).
* TECHNOLOGY axis exists but its vocabulary is intentionally empty until
  separate evidence arrives. ``LED`` is defined as technology (not a material
  and not a product type) and must not be added to the vocabulary yet.
* APPLICABILITY may legitimately stay ``UNKNOWN``; UNKNOWN is a valid state.
* ``PROCUREMENT_MODE=DIRECT`` disables product candidate generation entirely.
* Old discovery values normalize through :data:`LEGACY_PRODUCT_MIGRATIONS`
  (28 values) and never leak into canonical output.
* substring/regex discovery is a FIND_CANDIDATE signal only: it may never
  CONFIRM_PRODUCT / CONFIRM_OBJECT / SET_MEDAL.

Size note (AGENTS.md 450-line rule): this module intentionally exceeds 450
lines. It is a frozen vocabulary plus its legacy normalization table and small
projection helpers. Splitting the vocabulary out would recreate exactly the
second parallel registry this WIP exists to prevent, and the repo already keeps
the object authority (``expert_object_taxonomy.py``, 608 lines) in one file for
the same reason. The table is data, not logic; no behaviour is hidden in it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# --------------------------------------------------------------------------
# PRODUCT_FAMILY
# --------------------------------------------------------------------------
LIGHTING = "LIGHTING"
BARRIER_RAILING = "BARRIER_RAILING"
DRAINAGE = "DRAINAGE"
PIPES = "PIPES"
GRATING_AND_DECKING = "GRATING_AND_DECKING"

PRODUCT_FAMILY_VALUES: tuple[str, ...] = (
    LIGHTING,
    BARRIER_RAILING,
    DRAINAGE,
    PIPES,
    GRATING_AND_DECKING,
)

PRODUCT_FAMILY_LABELS: Mapping[str, str] = {
    LIGHTING: "Светотехника",
    BARRIER_RAILING: "Ограждения и барьеры",
    DRAINAGE: "Водоотвод",
    PIPES: "Трубы и трубопроводы",
    GRATING_AND_DECKING: "Настилы и решётки",
}

# --------------------------------------------------------------------------
# PRODUCT_TYPE  (exactly one family per type)
# --------------------------------------------------------------------------
LIGHTING_FIXTURE = "LIGHTING_FIXTURE"
LIGHTING_POLE = "LIGHTING_POLE"
LIGHTING_BRACKET = "LIGHTING_BRACKET"
LIGHTING_POLE_BASE_PROTECTOR = "LIGHTING_POLE_BASE_PROTECTOR"
ROAD_BARRIER = "ROAD_BARRIER"
RAILING = "RAILING"
TERRITORY_FENCE = "TERRITORY_FENCE"
DRAINAGE_TRAY = "DRAINAGE_TRAY"
STORM_WATER_INLET = "STORM_WATER_INLET"
DRAINAGE_PUMP = "DRAINAGE_PUMP"
PIPE = "PIPE"
GRATING = "GRATING"

PRODUCT_TYPES_BY_FAMILY: Mapping[str, tuple[str, ...]] = {
    LIGHTING: (LIGHTING_FIXTURE, LIGHTING_POLE, LIGHTING_BRACKET, LIGHTING_POLE_BASE_PROTECTOR),
    BARRIER_RAILING: (ROAD_BARRIER, RAILING, TERRITORY_FENCE),
    DRAINAGE: (DRAINAGE_TRAY, STORM_WATER_INLET, DRAINAGE_PUMP),
    PIPES: (PIPE,),
    GRATING_AND_DECKING: (GRATING,),
}

PRODUCT_TYPE_VALUES: tuple[str, ...] = tuple(
    product_type
    for family in PRODUCT_FAMILY_VALUES
    for product_type in PRODUCT_TYPES_BY_FAMILY[family]
)

PRODUCT_TYPE_FAMILY: Mapping[str, str] = {
    product_type: family
    for family, types in PRODUCT_TYPES_BY_FAMILY.items()
    for product_type in types
}

PRODUCT_TYPE_LABELS: Mapping[str, str] = {
    LIGHTING_FIXTURE: "Светильник",
    LIGHTING_POLE: "Опора освещения",
    LIGHTING_BRACKET: "Кронштейн светильника",
    LIGHTING_POLE_BASE_PROTECTOR: "Защита основания опоры освещения",
    ROAD_BARRIER: "Барьерное ограждение",
    RAILING: "Перильное ограждение",
    TERRITORY_FENCE: "Ограждение территории",
    DRAINAGE_TRAY: "Водоотводный лоток",
    STORM_WATER_INLET: "Дождеприёмник",
    DRAINAGE_PUMP: "Дренажный насос",
    PIPE: "Труба / трубопровод",
    GRATING: "Настил / решётка",
}

# --------------------------------------------------------------------------
# APPLICATION  ("where / on which object", never "what the product is")
# --------------------------------------------------------------------------
ROAD = "ROAD"
STREET = "STREET"
BRIDGE = "BRIDGE"
TUNNEL = "TUNNEL"
PARK = "PARK"
SQUARE = "SQUARE"
COURTYARD = "COURTYARD"
PLAYGROUND = "PLAYGROUND"
PARKING = "PARKING"
EMBANKMENT = "EMBANKMENT"
PEDESTRIAN_ZONE = "PEDESTRIAN_ZONE"
FACADE = "FACADE"
INDUSTRIAL = "INDUSTRIAL"
TERRITORY = "TERRITORY"
UTILITY_NETWORK = "UTILITY_NETWORK"
OTHER_URBAN = "OTHER_URBAN"

APPLICATION_VALUES: tuple[str, ...] = (
    ROAD,
    STREET,
    BRIDGE,
    TUNNEL,
    PARK,
    SQUARE,
    COURTYARD,
    PLAYGROUND,
    PARKING,
    EMBANKMENT,
    PEDESTRIAN_ZONE,
    FACADE,
    INDUSTRIAL,
    TERRITORY,
    UTILITY_NETWORK,
    OTHER_URBAN,
)

APPLICATION_LABELS: Mapping[str, str] = {
    ROAD: "автодорога",
    STREET: "улица / тротуар",
    BRIDGE: "мост / путепровод",
    TUNNEL: "тоннель",
    PARK: "парк",
    SQUARE: "сквер",
    COURTYARD: "дворовая территория",
    PLAYGROUND: "детская / спортивная площадка",
    PARKING: "парковка",
    EMBANKMENT: "набережная",
    PEDESTRIAN_ZONE: "пешеходная зона",
    FACADE: "фасад",
    INDUSTRIAL: "промышленная площадка",
    TERRITORY: "ограждаемая территория",
    UTILITY_NETWORK: "инженерная сеть",
    OTHER_URBAN: "прочее благоустройство",
}

# --------------------------------------------------------------------------
# MATERIAL  (4 confirmed; a material is never a product type)
# --------------------------------------------------------------------------
METAL = "METAL"
CONCRETE = "CONCRETE"
COMPOSITE = "COMPOSITE"
FIBERGLASS = "FIBERGLASS"

MATERIAL_VALUES: tuple[str, ...] = (METAL, CONCRETE, COMPOSITE, FIBERGLASS)

# Materials seen in raw text but NOT confirmed by the contract review. They are
# documented here so nobody silently promotes them; they are not canonical.
UNCONFIRMED_MATERIALS: tuple[str, ...] = (
    "POLYMER",
    "POLYMER_CONCRETE",
    "POLYMER_SAND",
    "WOOD",
    "WOOD_POLYMER",
)

# --------------------------------------------------------------------------
# VARIANT  (constructive execution; never a product type)
# --------------------------------------------------------------------------
LINEAR = "LINEAR"
WELL = "WELL"

VARIANT_VALUES: tuple[str, ...] = (LINEAR, WELL)

# --------------------------------------------------------------------------
# TECHNOLOGY  (axis reserved; vocabulary intentionally empty for now)
# --------------------------------------------------------------------------
TECHNOLOGY_VALUES: tuple[str, ...] = ()
RESERVED_TECHNOLOGY_CANDIDATES: tuple[str, ...] = ("LED",)

# --------------------------------------------------------------------------
# APPLICABILITY  (UNKNOWN is a valid, expected state)
# --------------------------------------------------------------------------
APPLICABILITY_YES = "YES"
APPLICABILITY_CONDITIONAL = "CONDITIONAL"
APPLICABILITY_NO = "NO"
APPLICABILITY_UNKNOWN = "UNKNOWN"

APPLICABILITY_VALUES: tuple[str, ...] = (
    APPLICABILITY_YES,
    APPLICABILITY_CONDITIONAL,
    APPLICABILITY_NO,
    APPLICABILITY_UNKNOWN,
)

# --------------------------------------------------------------------------
# PROCUREMENT_MODE  (DIRECT disables product candidate generation)
# --------------------------------------------------------------------------
PROCUREMENT_MODE_DIRECT = "DIRECT"
PROCUREMENT_MODE_OBJECT = "OBJECT"
PROCUREMENT_MODE_SERVICE_NO_OBJECT = "SERVICE_NO_OBJECT"
PROCUREMENT_MODE_AMBIGUOUS = "AMBIGUOUS"

PROCUREMENT_MODE_VALUES: tuple[str, ...] = (
    PROCUREMENT_MODE_DIRECT,
    PROCUREMENT_MODE_OBJECT,
    PROCUREMENT_MODE_SERVICE_NO_OBJECT,
    PROCUREMENT_MODE_AMBIGUOUS,
)

# Architecture rule: substring/regex discovery is candidate-only.
REGEX_AUTHORITY = "FIND_CANDIDATE_ONLY"
OBJECT_PATTERNS_FORBIDDEN_AS_PRIOR: Mapping[str, float] = {
    "SOCIAL_CARE": 0.85,
    "ENERGY_FACILITY": 0.40,
    "STREET": 0.30,
}


class ProductOntologyError(ValueError):
    """Raised when axes do not form a valid canonical product record."""


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def is_canonical_product_family(value: Any) -> bool:
    return _norm(value) in PRODUCT_FAMILY_VALUES


def is_canonical_product_type(value: Any, family: str | None = None) -> bool:
    code = _norm(value)
    if code not in PRODUCT_TYPE_FAMILY:
        return False
    if family is None:
        return True
    return PRODUCT_TYPE_FAMILY[code] == _norm(family)


def family_of_product_type(product_type: Any) -> str | None:
    return PRODUCT_TYPE_FAMILY.get(_norm(product_type))


def types_of_family(family: Any) -> tuple[str, ...]:
    return PRODUCT_TYPES_BY_FAMILY.get(_norm(family), ())


def is_canonical_application(value: Any) -> bool:
    return _norm(value) in APPLICATION_VALUES


def is_canonical_material(value: Any) -> bool:
    return _norm(value) in MATERIAL_VALUES


def is_canonical_variant(value: Any) -> bool:
    return _norm(value) in VARIANT_VALUES


def is_canonical_technology(value: Any) -> bool:
    return _norm(value) in TECHNOLOGY_VALUES


def is_valid_applicability(value: Any) -> bool:
    return _norm(value) in APPLICABILITY_VALUES


def product_candidate_generation_allowed(procurement_mode: Any) -> bool:
    """DIRECT purchases carry no embedded product: candidate generation is OFF."""
    return _norm(procurement_mode) != PROCUREMENT_MODE_DIRECT


def validate_product_axes(
    *,
    family: Any = None,
    product_type: Any = None,
    application: Any = None,
    material: Any = None,
    variant: Any = None,
    technology: Any = None,
) -> tuple[str, ...]:
    """Return a tuple of human-readable problems; empty means valid.

    None / empty strings are allowed for optional axes. Any non-empty value that
    is not canonical is an error: canonical output must not be free text.
    """
    problems: list[str] = []
    fam = _norm(family)
    ptype = _norm(product_type)

    if not fam:
        problems.append("PRODUCT_FAMILY is required")
    elif fam not in PRODUCT_FAMILY_VALUES:
        problems.append(f"unknown PRODUCT_FAMILY: {family!r}")

    if ptype:
        if ptype not in PRODUCT_TYPE_FAMILY:
            problems.append(f"unknown PRODUCT_TYPE: {product_type!r}")
        elif fam in PRODUCT_FAMILY_VALUES and PRODUCT_TYPE_FAMILY[ptype] != fam:
            problems.append(
                f"PRODUCT_TYPE {ptype} does not belong to PRODUCT_FAMILY {fam}"
            )
    else:
        problems.append("PRODUCT_TYPE is required")

    for axis, value, allowed in (
        ("APPLICATION", application, APPLICATION_VALUES),
        ("MATERIAL", material, MATERIAL_VALUES),
        ("VARIANT", variant, VARIANT_VALUES),
        ("TECHNOLOGY", technology, TECHNOLOGY_VALUES),
    ):
        code = _norm(value)
        if code and code not in allowed:
            problems.append(f"unknown {axis}: {value!r}")

    return tuple(problems)


def assert_product_axes(**axes: Any) -> None:
    problems = validate_product_axes(**axes)
    if problems:
        raise ProductOntologyError("; ".join(problems))


def normalize_product_axes(
    *,
    family: Any = None,
    product_type: Any = None,
    application: Any = None,
    material: Any = None,
    variant: Any = None,
    technology: Any = None,
) -> dict[str, str | None]:
    """Return canonical axis codes (upper-case) or raise ProductOntologyError."""
    assert_product_axes(
        family=family,
        product_type=product_type,
        application=application,
        material=material,
        variant=variant,
        technology=technology,
    )
    return {
        "product_family": _norm(family),
        "product_type": _norm(product_type),
        "application": _norm(application) or None,
        "material": _norm(material) or None,
        "variant": _norm(variant) or None,
        "technology": _norm(technology) or None,
    }


def ontology_stats() -> dict[str, int]:
    return {
        "product_families": len(PRODUCT_FAMILY_VALUES),
        "product_types": len(PRODUCT_TYPE_VALUES),
        "application_values": len(APPLICATION_VALUES),
        "material_values": len(MATERIAL_VALUES),
        "variant_values": len(VARIANT_VALUES),
        "technology_values": len(TECHNOLOGY_VALUES),
    }
# --------------------------------------------------------------------------
# LEGACY / DISCOVERY NORMALIZATION  (explicit mapping for 28 old values)
# --------------------------------------------------------------------------
KEEP_AS_PRODUCT_TYPE = "KEEP_AS_PRODUCT_TYPE"
RENAME = "RENAME"
MOVE_TO_APPLICATION = "MOVE_TO_APPLICATION"
MOVE_TO_MATERIAL = "MOVE_TO_MATERIAL"
MOVE_TO_VARIANT = "MOVE_TO_VARIANT"
DROP_AS_FALSE_SIGNAL = "DROP_AS_FALSE_SIGNAL"

LEGACY_DECISION_VALUES: tuple[str, ...] = (
    KEEP_AS_PRODUCT_TYPE,
    RENAME,
    MOVE_TO_APPLICATION,
    MOVE_TO_MATERIAL,
    MOVE_TO_VARIANT,
    DROP_AS_FALSE_SIGNAL,
)


@dataclass(frozen=True)
class LegacyProductMigration:
    """One explicit destination for an old discovery product value."""

    old_value: str
    decision: str
    family: str | None = None
    product_type: str | None = None
    application: str | None = None
    application_options: tuple[str, ...] = ()
    material_options: tuple[str, ...] = ()
    variant: str | None = None
    note: str = ""

    @property
    def dropped(self) -> bool:
        return self.decision == DROP_AS_FALSE_SIGNAL


def _m(
    old_value: str,
    decision: str,
    family: str | None = None,
    product_type: str | None = None,
    application: str | None = None,
    application_options: tuple[str, ...] = (),
    material_options: tuple[str, ...] = (),
    variant: str | None = None,
    note: str = "",
) -> LegacyProductMigration:
    return LegacyProductMigration(
        old_value=old_value,
        decision=decision,
        family=family,
        product_type=product_type,
        application=application,
        application_options=application_options,
        material_options=material_options,
        variant=variant,
        note=note,
    )


LEGACY_PRODUCT_MIGRATIONS: Mapping[str, LegacyProductMigration] = {
    m.old_value: m
    for m in (
        # LIGHTING: object-typed systems become APPLICATION on one product type
        _m("ROAD_LIGHTING", MOVE_TO_APPLICATION, LIGHTING, LIGHTING_FIXTURE, ROAD),
        _m("STREET_LIGHTING", MOVE_TO_APPLICATION, LIGHTING, LIGHTING_FIXTURE, STREET),
        _m("PARK_LIGHTING", MOVE_TO_APPLICATION, LIGHTING, LIGHTING_FIXTURE, PARK),
        _m("TUNNEL_LIGHTING", MOVE_TO_APPLICATION, LIGHTING, LIGHTING_FIXTURE, TUNNEL),
        _m("PARKING_LIGHTING", MOVE_TO_APPLICATION, LIGHTING, LIGHTING_FIXTURE, PARKING),
        _m("FACADE_LIGHTING", MOVE_TO_APPLICATION, LIGHTING, LIGHTING_FIXTURE, FACADE),
        _m("INDUSTRIAL_LIGHTING", MOVE_TO_APPLICATION, LIGHTING, LIGHTING_FIXTURE, INDUSTRIAL),
        _m(
            "URBAN_LIGHTING",
            MOVE_TO_APPLICATION,
            LIGHTING,
            LIGHTING_FIXTURE,
            OTHER_URBAN,
            (COURTYARD, PLAYGROUND, EMBANKMENT, OTHER_URBAN),
            note="generic fallback; covered courtyard/playground/embankment",
        ),
        _m(
            "LIGHTING_FIXTURE",
            KEEP_AS_PRODUCT_TYPE,
            LIGHTING,
            LIGHTING_FIXTURE,
            note="LED is a reserved TECHNOLOGY candidate, not frozen",
        ),
        _m(
            "LIGHTING_POLE",
            KEEP_AS_PRODUCT_TYPE,
            LIGHTING,
            LIGHTING_POLE,
            None,
            (STREET, PARK),
            (METAL,),
            note="lighting pole only; never a power-transmission pole",
        ),
        _m(
            "LIGHTING_BRACKET",
            KEEP_AS_PRODUCT_TYPE,
            LIGHTING,
            LIGHTING_BRACKET,
            None,
            (ROAD, STREET),
            (METAL,),
        ),
        _m(
            "LIGHTING_POLE_BASE_PROTECTOR",
            KEEP_AS_PRODUCT_TYPE,
            LIGHTING,
            LIGHTING_POLE_BASE_PROTECTOR,
            None,
            (),
            (COMPOSITE,),
            note="evidence=0 (UNKNOWN)",
        ),
        # BARRIER / RAILING: object of application moves to APPLICATION
        _m(
            "ROAD_BARRIER",
            KEEP_AS_PRODUCT_TYPE,
            BARRIER_RAILING,
            ROAD_BARRIER,
            None,
            (ROAD, STREET, BRIDGE),
            (METAL,),
        ),
        _m(
            "BRIDGE_BARRIER",
            MOVE_TO_APPLICATION,
            BARRIER_RAILING,
            ROAD_BARRIER,
            BRIDGE,
            (),
            (METAL,),
        ),
        _m(
            "PEDESTRIAN_RAILING",
            RENAME,
            BARRIER_RAILING,
            RAILING,
            None,
            (STREET, PEDESTRIAN_ZONE, COURTYARD, PLAYGROUND),
            (METAL, COMPOSITE),
            note="renamed to short canonical RAILING",
        ),
        _m(
            "BRIDGE_RAILING",
            MOVE_TO_APPLICATION,
            BARRIER_RAILING,
            RAILING,
            BRIDGE,
            (),
            (METAL, COMPOSITE),
        ),
        _m(
            "STREET_RAILING",
            RENAME,
            BARRIER_RAILING,
            TERRITORY_FENCE,
            TERRITORY,
            (),
            (METAL,),
            note="in fact a territory fence, not a street railing",
        ),
        # COMPOSITES: material axis, never a product type
        _m(
            "COMPOSITE_RAILING",
            MOVE_TO_MATERIAL,
            BARRIER_RAILING,
            RAILING,
            None,
            (STREET, ROAD, PEDESTRIAN_ZONE),
            (COMPOSITE,),
        ),
        _m(
            "COMPOSITE_DRAINAGE_TRAY",
            MOVE_TO_MATERIAL,
            DRAINAGE,
            DRAINAGE_TRAY,
            None,
            (),
            (COMPOSITE,),
        ),
        _m(
            "COMPOSITE_PIPE",
            MOVE_TO_MATERIAL,
            PIPES,
            PIPE,
            UTILITY_NETWORK,
            (),
            (COMPOSITE, FIBERGLASS),
        ),
        # DRAINAGE: product vs application vs variant
        _m(
            "DRAINAGE_TRAY",
            KEEP_AS_PRODUCT_TYPE,
            DRAINAGE,
            DRAINAGE_TRAY,
            None,
            (ROAD, STREET, COURTYARD, PARK, PARKING, PEDESTRIAN_ZONE),
            (CONCRETE, METAL),
        ),
        _m("LINEAR_DRAINAGE", MOVE_TO_VARIANT, DRAINAGE, DRAINAGE_TRAY, None, (), (), LINEAR),
        _m("ROAD_DRAINAGE", MOVE_TO_APPLICATION, DRAINAGE, DRAINAGE_TRAY, ROAD),
        _m("BRIDGE_DRAINAGE", MOVE_TO_APPLICATION, DRAINAGE, DRAINAGE_TRAY, BRIDGE),
        _m(
            "DRAINAGE_CHANNEL",
            DROP_AS_FALSE_SIGNAL,
            note="substring канализации->канал; kanava is earthwork (8/8 FP)",
        ),
        _m(
            "STORM_WATER_INLET",
            KEEP_AS_PRODUCT_TYPE,
            DRAINAGE,
            STORM_WATER_INLET,
            None,
            (ROAD, UTILITY_NETWORK),
            (),
            WELL,
        ),
        _m("DRAINAGE_WELL", MOVE_TO_VARIANT, DRAINAGE, STORM_WATER_INLET, None, (), (), WELL),
        _m("DRAINAGE_PUMP", KEEP_AS_PRODUCT_TYPE, DRAINAGE, DRAINAGE_PUMP, None, (), (), None),
    )
}

LEGACY_DISCOVERY_VALUES: tuple[str, ...] = tuple(LEGACY_PRODUCT_MIGRATIONS)


def legacy_migration_counts() -> dict[str, int]:
    counts: dict[str, int] = {decision: 0 for decision in LEGACY_DECISION_VALUES}
    for migration in LEGACY_PRODUCT_MIGRATIONS.values():
        counts[migration.decision] = counts.get(migration.decision, 0) + 1
    counts["TOTAL"] = len(LEGACY_PRODUCT_MIGRATIONS)
    return counts


def migrate_legacy_product(old_value: Any) -> dict[str, str | None] | None:
    """Map an old discovery value onto canonical axes.

    Returns a dict with ``product_family`` / ``product_type`` / ``application`` /
    ``material`` / ``variant`` / ``technology`` plus ``decision`` and
    ``dropped``. Returns ``None`` for a value that is not a known legacy value.
    """
    migration = LEGACY_PRODUCT_MIGRATIONS.get(_norm(old_value))
    if migration is None:
        return None
    material = migration.material_options[0] if len(migration.material_options) == 1 else None
    return {
        "legacy_value": migration.old_value,
        "decision": migration.decision,
        "dropped": migration.dropped,
        "product_family": migration.family,
        "product_type": migration.product_type,
        "application": migration.application,
        "material": material,
        "variant": migration.variant,
        "technology": None,
    }


def validate_legacy_migrations() -> tuple[str, ...]:
    problems: list[str] = []
    for value, migration in LEGACY_PRODUCT_MIGRATIONS.items():
        if migration.decision not in LEGACY_DECISION_VALUES:
            problems.append(f"{value}: unknown decision {migration.decision!r}")
        if migration.dropped:
            continue
        problems.extend(
            f"{value}: {problem}"
            for problem in validate_product_axes(
                family=migration.family,
                product_type=migration.product_type,
                application=migration.application,
                variant=migration.variant,
            )
        )
        for option in migration.application_options:
            if not is_canonical_application(option):
                problems.append(f"{value}: non-canonical application option {option!r}")
        for option in migration.material_options:
            if not is_canonical_material(option):
                problems.append(f"{value}: non-canonical material option {option!r}")
        if migration.application and migration.application not in migration.application_options:
            if migration.application_options:
                problems.append(f"{value}: application {migration.application} not in options")
    return tuple(problems)


# --------------------------------------------------------------------------
# USER-FACING PROJECTION  (labels are not new product types)
# --------------------------------------------------------------------------
_LIGHTING_LABELS: Mapping[str, str] = {
    ROAD: "Дорожное освещение",
    STREET: "Уличное освещение",
    PARK: "Парковое освещение",
    SQUARE: "Освещение сквера",
    TUNNEL: "Тоннельное освещение",
    PARKING: "Освещение парковки",
    BRIDGE: "Мостовое освещение",
    FACADE: "Фасадное освещение",
    INDUSTRIAL: "Промышленное освещение",
    COURTYARD: "Дворовое освещение",
    PLAYGROUND: "Освещение площадки",
    EMBANKMENT: "Освещение набережной",
    PEDESTRIAN_ZONE: "Пешеходное освещение",
    TERRITORY: "Освещение территории",
    UTILITY_NETWORK: "Освещение сетей",
    OTHER_URBAN: "Наружное освещение",
}

_MATERIAL_ADJ_NEUTER: Mapping[str, str] = {
    COMPOSITE: "Композитное",
    METAL: "Металлическое",
    FIBERGLASS: "Стеклопластиковое",
    CONCRETE: "Бетонное",
}

_MATERIAL_ADJ_MASC: Mapping[str, str] = {
    COMPOSITE: "Композитный",
    METAL: "Металлический",
    FIBERGLASS: "Стеклопластиковый",
    CONCRETE: "Бетонный",
}

_APPLICATION_ADJ_NEUTER: Mapping[str, str] = {
    ROAD: "дорожное",
    STREET: "уличное",
    BRIDGE: "мостовое",
    TUNNEL: "тоннельное",
    PARK: "парковое",
    SQUARE: "скверовое",
    COURTYARD: "дворовое",
    PLAYGROUND: "площадочное",
    PARKING: "парковочное",
    EMBANKMENT: "набережное",
    PEDESTRIAN_ZONE: "пешеходное",
    TERRITORY: "территориальное",
    INDUSTRIAL: "промышленное",
    FACADE: "фасадное",
    UTILITY_NETWORK: "сетевое",
    OTHER_URBAN: "городское",
}


def user_facing_label(
    *,
    product_type: Any,
    application: Any = None,
    material: Any = None,
    variant: Any = None,
) -> str:
    """Compose a human label from canonical axes; never a new product type."""
    ptype = _norm(product_type)
    app = _norm(application)
    mat = _norm(material)
    var = _norm(variant)

    if ptype == LIGHTING_FIXTURE:
        if app in _LIGHTING_LABELS:
            return _LIGHTING_LABELS[app]
        return "Наружное освещение"
    if ptype == LIGHTING_POLE:
        base = "Опора освещения"
        if app in APPLICATION_LABELS:
            return f"{base} ({APPLICATION_LABELS[app]})"
        return base
    if ptype in (RAILING, ROAD_BARRIER):
        base = "перильное ограждение" if ptype == RAILING else "барьерное ограждение"
        parts: list[str] = []
        if mat in _MATERIAL_ADJ_NEUTER:
            parts.append(_MATERIAL_ADJ_NEUTER[mat])
        if app in _APPLICATION_ADJ_NEUTER:
            parts.append(_APPLICATION_ADJ_NEUTER[app])
        parts.append(base)
        if var:
            parts.append(f"({var})")
        return " ".join(parts)
    if ptype == DRAINAGE_TRAY:
        parts = []
        if mat in _MATERIAL_ADJ_MASC:
            parts.append(_MATERIAL_ADJ_MASC[mat])
        if var:
            parts.append("линейный")
        parts.append("водоотводный лоток")
        if app in APPLICATION_LABELS:
            parts.append(f"({APPLICATION_LABELS[app]})")
        return " ".join(parts)
    if ptype == TERRITORY_FENCE:
        return "Ограждение территории"
    if ptype == STORM_WATER_INLET:
        return "Дождеприёмный колодец" if var == WELL else "Дождеприёмник"
    return PRODUCT_TYPE_LABELS.get(ptype, ptype or "UNKNOWN")
