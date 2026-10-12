"""Canonical production Object Layer: PROCUREMENT -> PROCUREMENT_MODE -> OBJECT.

WIP=CANONICAL-OBJECT-LAYER-PRODUCTION-V1.

This module is the only authority that turns a procurement into a canonical
object row.  It does *not* classify with a model: it applies boundary-safe
deterministic rules over the procurement title and it accepts an already
canonical object claim from an allowed provenance source.

Hard rules
----------
1. Procurement mode gate comes first.  DIRECT and SERVICE_NO_OBJECT have no
   object lifecycle at all (``object_applicable = False``, OBJECT_* = N/A).
   AMBIGUOUS / unknown mode is never auto-classified.  Buying a finished
   dwelling is DIRECT even when the scope authority says WORKS (see
   ``product_candidate_materializer.is_dwelling_acquisition`` / ``is_dwelling_acquisition_by_subject``).
2. A canonical code is emitted only when it validates against
   ``expert_object_taxonomy``.  No taxonomy value is invented here.
3. Matching is token / phrase boundary-safe (``re`` word boundaries over the
   folded text), never a bare substring: отмостка is not a bridge, парковка is
   not a park, дорогостоящий is not a road, an address street is not STREET.
4. Conflicting equally ranked rules are an explicit OBJECT_CONFLICT.  They are
   never written and never silently resolved.

``OBJECT_CLASSIFICATION_VERSION`` lets Layer 1 product candidates point at the
exact object-layer revision that produced them.

Size note: the module is ~400 lines and stays one file on purpose.  The
boundary-safe rule table, the context/application-area tables, the mode gate
and the storage-row validator are one contract; splitting the vocabulary out
would recreate the parallel enum this project layer removes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from src.services import expert_object_taxonomy as OT
from src.services.product_candidate_materializer import ALLOWED_OBJECT_SOURCES as _MAT_ALLOWED
from src.services.product_candidate_materializer import MODE_SOURCE_ACQUISITION
from src.services.product_candidate_materializer import MODE_SOURCE_SUBJECT_ACQUISITION
from src.services.product_candidate_materializer import resolve_procurement_mode_with_source

OBJECT_CLASSIFICATION_VERSION = "object_canonical_v1"
OBJECT_LAYER_AUTHORITY = "src/services/object_classification.py"
CLASSIFICATION_TABLE = "crm_procurement_object_classifications"

# --- classification provenance (source priority A..E) -----------------------
SOURCE_EXPERT_CONFIRMED = "EXPERT_CONFIRMED"
SOURCE_REVIEWED_HISTORICAL = "REVIEWED"
SOURCE_DETERMINISTIC = "DETERMINISTIC_HIGH_CONFIDENCE"
SOURCE_CANONICAL_EXISTING = "CANONICAL_CURRENT"
SOURCE_UNRESOLVED = "UNRESOLVED"
# Model provenance (WIP=MASS-CANONICAL-OBJECT-LAYER-RUN-V1 section 8).  Two
# distinct labels so a model-resolved OBJECT is never confused with a model
# that only resolved the procurement MODE.
SOURCE_QWEN_OBJECT = "QWEN_OBJECT_V1"
SOURCE_QWEN_MODE = "QWEN_MODE_V1"

# Only the first three may confirm an object for Layer 1.  Regex/substring
# discovery is deliberately absent: it may FIND an object, never CONFIRM one.
# Derived from the deployed Layer 1 policy so the two layers share exactly one
# object-source vocabulary (product_candidate_materializer.ALLOWED_OBJECT_SOURCES).
ALLOWED_CLASSIFICATION_SOURCES: tuple[str, ...] = tuple(_MAT_ALLOWED) + (SOURCE_QWEN_MODE,)

# --- classification statuses ------------------------------------------------
STATUS_RESOLVED_REVIEWED = "RESOLVED_REVIEWED"
STATUS_RESOLVED_HIGH_CONFIDENCE = "RESOLVED_HIGH_CONFIDENCE"
STATUS_RESOLVED_MODEL = "RESOLVED_MODEL"
STATUS_DIRECT_NA = "DIRECT_NA"
STATUS_SERVICE_NA = "SERVICE_NA"
# Mode could not be resolved as OBJECT (deterministic UNKNOWN/AMBIGUOUS, or a
# model that returned AMBIGUOUS).  Named MODE_AMBIGUOUS per the mass-run
# contract; STATUS_AMBIGUOUS is kept as the historical alias.
STATUS_MODE_AMBIGUOUS = "MODE_AMBIGUOUS"
STATUS_AMBIGUOUS = STATUS_MODE_AMBIGUOUS
STATUS_OBJECT_MISSING = "OBJECT_MISSING"
STATUS_OBJECT_CONFLICT = "OBJECT_CONFLICT"
STATUS_OBJECT_UNCERTAIN = "OBJECT_UNCERTAIN"
STATUS_MODEL_INVALID = "MODEL_INVALID"
STATUS_OBJECT_NONCANONICAL = "OBJECT_NONCANONICAL"

CLASSIFICATION_STATUS_VALUES: tuple[str, ...] = (
    STATUS_RESOLVED_REVIEWED,
    STATUS_RESOLVED_HIGH_CONFIDENCE,
    STATUS_RESOLVED_MODEL,
    STATUS_DIRECT_NA,
    STATUS_SERVICE_NA,
    STATUS_MODE_AMBIGUOUS,
    STATUS_OBJECT_MISSING,
    STATUS_OBJECT_CONFLICT,
    STATUS_OBJECT_UNCERTAIN,
    STATUS_MODEL_INVALID,
    STATUS_OBJECT_NONCANONICAL,
)

# Statuses that carry a canonical OBJECT_TYPE and may feed Layer 1.
RESOLVED_STATUSES: tuple[str, ...] = (
    STATUS_RESOLVED_REVIEWED,
    STATUS_RESOLVED_HIGH_CONFIDENCE,
    STATUS_RESOLVED_MODEL,
)

# Statuses with no OBJECT_TYPE at all (missing/uncertain/invalid object).
UNRESOLVED_STATUSES: tuple[str, ...] = (
    STATUS_MODE_AMBIGUOUS,
    STATUS_OBJECT_MISSING,
    STATUS_OBJECT_CONFLICT,
    STATUS_OBJECT_UNCERTAIN,
    STATUS_MODEL_INVALID,
    STATUS_OBJECT_NONCANONICAL,
)

CONFIDENCE_EXPERT = "EXPERT"
CONFIDENCE_MODEL = "MODEL"
CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_NONE = "NONE"

NA = OT.OBJECT_NOT_APPLICABLE


# Reference noise: address tokens and landmark references.  An address street
# name ("ул. Заводская") or a landmark ("в районе магазина X") must never create
# an OBJECT_TYPE of its own (section 7 known bad patterns).
_NOISE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bул\.?\s+[а-яa-z0-9\-]+"),
    re.compile(r"\bулиц\w*\s+[а-яa-z0-9\-]+"),
    re.compile(
        r"\b(?:проспект|пр-т|пр-кт|переулок|пер\.|шоссе|ш\.|проезд|бульвар|б-р|"
        r"пл\.|площадь|наб\.|микрорайон|мкр\.?)\s+[а-яa-z0-9\-]+"
    ),
    re.compile(r"\b(?:г|п|с|рп|пос|ст|д)\.\s*[а-яa-z0-9\-]+"),
    re.compile(r"\bд\.\s*\d+[а-я]?"),
    re.compile(r"\bв\s+районе\s+(?:[а-яa-z0-9\-]+\s+){0,2}"),
    re.compile(r"\([^)]*\)"),
)


def _strip_reference_noise(folded: str) -> str:
    """Remove address / landmark fragments before deterministic matching."""
    cleaned = folded
    for pattern in _NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()

def _fold(text: Any) -> str:
    """Lowercase, fold ё and collapse whitespace.  Tokens are never dropped."""
    value = str(text or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", value).strip()


# --- deterministic rules ----------------------------------------------------
# (priority, pattern, sector, object_type, object_subtype).  Highest priority
# wins; equal-priority matches with different object types are a conflict.
# Every pattern is anchored with \b so a substring can never fire.
_ENDPOINT_REF = (
    r"(?<![–—-]\s)(?<!\bк\s)(?<!\bдо\s)(?<!\bчерез\s)"
    r"(?<!\bтерритории\s)(?<!\bтерритория\s)(?<!\bтерриторий\s)"
)

# "бывший аэропорт" / "бывшая железная дорога" is a *former* object, not the
# object of the procurement (the classic case being new construction on the
# site of a decommissioned one).  Python lookbehind is fixed-width, so the
# common declensions are enumerated instead of using a variable-width stem.
_FORMER_REF = (
    r"(?<!\bбывшего\s)(?<!\bбывшему\s)(?<!\bбывшей\s)"
    r"(?<!\bбывшем\s)(?<!\bбывшим\s)(?<!\bбывшая\s)"
    r"(?<!\bбывший\s)(?<!\bбывшее\s)(?<!\bбывшие\s)"
    r"(?<!\bбывших\s)(?<!\bбывшую\s)"
)

_RULES: tuple[tuple[int, str, str, str, str | None], ...] = (
    (100, r"\bпутепровод\w*", OT.INFRASTRUCTURE, "BRIDGE", None),
    (100, r"\bэстакад\w*", OT.INFRASTRUCTURE, "BRIDGE", None),
    (100, r"\bмост(?:а|у|ом|е|ы|ов|ам|ами|ах|ик|ике|ика)?\b", OT.INFRASTRUCTURE, "BRIDGE", None),
    (100, r"\bтоннел\w*|\bтуннел\w*", OT.INFRASTRUCTURE, "TUNNEL", None),
    (99, r"\bмостов\w*\s+(?:переход\w*|сооружени\w*)", OT.INFRASTRUCTURE, "BRIDGE", None),
    (100, r"\bразвязк\w*", OT.INFRASTRUCTURE, "INTERCHANGE", None),
    (100, _ENDPOINT_REF + _FORMER_REF + r"\bжелезн\w*\s+дорог\w*|" + _ENDPOINT_REF + _FORMER_REF
     + r"\bжелезнодорожн\w*\s+(?:пут\w*|станц\w*|вокзал\w*|переезд\w*|платформ\w*|депо|полотн\w*|лини\w*|ветк\w*|сет\w*|мост\w*|узл\w*|инфраструктур\w*|транспорт\w*|сооружени\w*|хозяйств\w*|путепровод\w*|насып\w*|перегон\w*)",
     OT.INFRASTRUCTURE, "RAILWAY", None),
    (100, _ENDPOINT_REF + _FORMER_REF
     + r"(?:\bаэропорт\w*|\bаэродром\w*)", OT.INFRASTRUCTURE, "AIRPORT", None),
    # Noun forms only: an adjective stem must not fire (Газопроводское is a
    # settlement name, not a pipeline).  Adjectival usage needs the network noun.
    (98, r"\bтеплосет\w*|\bтеплов\w*\s+сет\w*|\bтеплотрасс\w*|\bтепломагистрал\w*|\bтеплоснабжени\w*",
     OT.INFRASTRUCTURE, "UTILITY_NETWORKS", "HEATING_NETWORK"),
    (98, r"\bводопровод(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b|\bводовод\w*|\bводоснабжени\w*|"
         r"\bводопроводн\w*\s+(?:сет\w*|сооружени\w*)",
     OT.INFRASTRUCTURE, "UTILITY_NETWORKS", "WATER_NETWORK"),
    (98, r"\bканализаци\w*|\bканализационн\w*\s+(?:сет\w*|сооружени\w*|насосн\w*|станц\w*)|"
         r"\bливнев\w*\s+(?:сет\w*|канализаци\w*|сток\w*)|\bливневк\w*",
     OT.INFRASTRUCTURE, "UTILITY_NETWORKS", "SEWER_NETWORK"),
    (98, r"\bгазопровод(?:а|у|ом|е|ы|ов|ам|ами|ах)?\b|\bгазоснабжени\w*|\bгазификаци\w*|"
         r"\bгазораспределительн\w*",
     OT.INFRASTRUCTURE, "UTILITY_NETWORKS", "GAS_NETWORK"),
    (98, r"\bкабельн\w*\s+лини\w*|\bлэп\b|\bэлектросет\w*|"
         r"\bвоздушн\w*\s+лини\w*\s+электропередач\w*|\bэлектропередач\w*",
     OT.INFRASTRUCTURE, "UTILITY_NETWORKS", "POWER_NETWORK"),
    (98, r"\bсет\w*\s+связи\b|\bоптико-волоконн\w*|\bволс\b",
     OT.INFRASTRUCTURE, "UTILITY_NETWORKS", "COMMUNICATION_NETWORK"),
    (95, r"\bавтодорог\w*|\bавтомобильн\w*\s+дорог\w*", OT.INFRASTRUCTURE, "ROAD", None),
    (95, r"\bдорог(?:а|и|у|е|ой|ою|ам|ами|ах)?\b", OT.INFRASTRUCTURE, "ROAD", None),
    (94, r"\bдорожн\w*\s+(?:покрыти\w*|одежд\w*)", OT.INFRASTRUCTURE, "ROAD", "ROAD_PAVEMENT"),
    (90, r"\bводозабор\w*|\bочистн\w*\s+сооружени\w*",
     OT.INFRASTRUCTURE, "MUNICIPAL_INFRASTRUCTURE", None),
    (92, r"\bдетск\w*\s+сад\w*|\bдетсад\w*|\bдошкольн\w*", OT.SOCIAL, "KINDERGARTEN", None),
    (91, r"\bшкол(?:а|ы|е|у|ой|ам|ами|ах)\b|\bшкольн\w*|\bобщеобразовательн\w*",
     OT.SOCIAL, "SCHOOL", None),
    (90, r"\bбольниц\w*|\bгоспитал\w*", OT.SOCIAL, "HOSPITAL", None),
    (90, r"\bполиклиник\w*|\bамбулатор\w*", OT.SOCIAL, "POLYCLINIC", None),
    (90, r"\bдиспансер\w*", OT.SOCIAL, "DISPENSARY", None),
    (90, r"\bколледж\w*|\bтехникум\w*|\bучилищ\w*|\bспо\b", OT.SOCIAL, "COLLEGE", None),
    (89, r"\bуниверситет\w*|\bвуз\b", OT.SOCIAL, "UNIVERSITY", None),
    (68, r"\bбиблиотек\w*|\bдом\w*\s+культур\w*|\bмузе\w*|\bтеатр\w*",
     OT.SOCIAL, "CULTURE_FACILITY", None),
    # A sports facility needs a sports building/construction noun: "спортивная
    # площадка" is a playground (URBAN_IMPROVEMENT), not a sports facility.
    (88, r"\bспорт(?:ивн\w*\s+(?:зал\w*|комплекс\w*|сооружени\w*|школ\w*|центр\w*|"
         r"интернат\w*|баз\w*)|зал\w*|комплекс\w*|сооружени\w*)|"
         r"\bфизкультурн\w*|\bстадион\w*",
     OT.SOCIAL, "SPORTS_FACILITY", None),
    (88, r"\bинтернат\w*|\bдетск\w*\s+дом\b|\bдом\w*\s+престарел\w*|\bсоцзащит\w*",
     OT.SOCIAL, "SOCIAL_CARE", None),
    (87, r"\bмкд\b|\bмногоквартирн\w*|\bжил(?:ой|ого|ому|ым|ом|ые|ых)\s+дом\w*",
     OT.RESIDENTIAL, "APARTMENT_BUILDING", None),
    (86, r"\bжил(?:ой|ого)\s+комплекс\w*", OT.RESIDENTIAL, "RESIDENTIAL_COMPLEX", None),
    (86, r"\bобщежит\w*", OT.RESIDENTIAL, "DORMITORY", None),
    (85, r"\bквартир\w*|\bжил(?:ое|ого|ых)\s+помещени\w*", OT.RESIDENTIAL, "RESIDENTIAL_UNIT", None),
    (84, r"\bторгов\w*\s+(?:центр\w*|комплекс\w*)|\bтц\b|\bмагазин\w*",
     OT.COMMERCIAL, "SHOPPING_CENTER", None),
    (83, r"\bсклад\w*|\bлогистическ\w*\s+комплекс\w*", OT.COMMERCIAL, "WAREHOUSE", None),
    (83, r"\bгостиниц\w*|\bотел\w*", OT.COMMERCIAL, "HOTEL", None),
    (82, r"\bофис\w*", OT.COMMERCIAL, "OFFICE", None),
    (80, r"\bкотельн\w*|\bтэц\b|\bгрэс\b|\bподстанц\w*|\bэнергоцентр\w*",
     OT.INDUSTRIAL, "ENERGY_FACILITY", None),
    (79, r"\bзавод\w*|\bфабрик\w*|\bкомбинат\w*", OT.INDUSTRIAL, "FACTORY", None),
    (78, r"\bпроизводственн\w*\s+корпус\w*|\bцех\w*", OT.INDUSTRIAL, "PRODUCTION_BUILDING", None),
    (77, r"\bпромплощад(?:к|ок)\w*|\bпромышленн\w*\s+территор\w*|\bпромзон\w*",
     OT.INDUSTRIAL, "INDUSTRIAL_SITE", None),
    # "индустриальный парк" / "промышленный парк" / "технопарк" is an
    # industrial site, never a municipal PARK (section 7 known bad patterns).
    (90, r"\bиндустриальн\w*\s+парк\w*|\bпромышленн\w*\s+парк\w*|"
         r"\bтехнопарк\w*", OT.INDUSTRIAL, "INDUSTRIAL_SITE", None),
    (76, r"\bпарк(?:а|у|ом|е|и|ов|ам|ами|ах)?\b|\bлесопарк\w*", OT.URBAN_IMPROVEMENT, "PARK", None),
    (75, r"\bсквер\w*", OT.URBAN_IMPROVEMENT, "SQUARE", None),
    (75, r"\bнабережн\w*", OT.URBAN_IMPROVEMENT, "EMBANKMENT", None),
    (74, r"\bдетск\w*\s+площадк\w*|\bигров\w*\s+площадк\w*|"
         r"\bспортивн\w*\s+площадк\w*|"
         r"\b(?:детск|игров|спортивн)\w*\b[\w\s,\-]{0,45}?\bплощад(?:к|ок)\w*",
     OT.URBAN_IMPROVEMENT, "PLAYGROUND", None),
    (73, r"\bпешеходн\w*\s+(?:зон\w*|дорожк\w*|улиц\w*)",
     OT.URBAN_IMPROVEMENT, "PEDESTRIAN_ZONE", None),
    (72, r"\bдворов\w*\s+территор\w*|\bпридомов\w*\s+территор\w*",
     OT.URBAN_IMPROVEMENT, "COURTYARD", None),
    (71, r"\bтротуар\w*", OT.INFRASTRUCTURE, "STREET", None),
    (70, r"\bблагоустройств\w*\s+улиц\w*|\bуличн\w*\s+благоустройств\w*",
     OT.URBAN_IMPROVEMENT, "STREETSCAPE", None),
    (66, r"\bобщественн\w*\s+пространств\w*", OT.URBAN_IMPROVEMENT, "PUBLIC_SPACE", None),
    (65, r"\bозеленени\w*", OT.URBAN_IMPROVEMENT, "GREEN_AREA", None),
    (60, r"\bблагоустройств\w*", OT.URBAN_IMPROVEMENT, "OTHER_URBAN_IMPROVEMENT", None),
)

_COMPILED: tuple[tuple[int, re.Pattern[str], str, str, str | None], ...] = tuple(
    (priority, re.compile(pattern), sector, object_type, subtype)
    for priority, pattern, sector, object_type, subtype in _RULES
)

# OBJECT_CONTEXT = environment the object sits in.  A network kind is always an
# OBJECT_SUBTYPE, never a context; a territory context never replaces the
# primary object.
_CONTEXT_TERMS: tuple[tuple[str, str], ...] = (
    ("landscaping", r"\bблагоустройств\w*|\bозеленени\w*"),
    ("courtyard", r"\bдворов\w*"),
    ("parking_area", r"\bпарковк\w*|\bавтостоянк\w*"),
    ("roof", r"\bкровл\w*|\bкрыш\w*"),
    ("external_territory", r"\bприлегающ\w*\s+территор\w*"),
)
_CONTEXT_COMPILED = tuple((code, re.compile(pattern)) for code, pattern in _CONTEXT_TERMS)

# APPLICATION_AREA = which part of the object is touched.
_APPLICATION_AREA_TERMS: tuple[tuple[str, str], ...] = (
    ("roof", r"\bкровл\w*"),
    ("basement", r"\bподвал\w*"),
    ("facade", r"\bфасад\w*"),
)
_APPLICATION_AREA_COMPILED = tuple(
    (code, re.compile(pattern)) for code, pattern in _APPLICATION_AREA_TERMS
)


@dataclass(frozen=True, slots=True)
class ObjectClassification:
    """One canonical object-layer row for a procurement."""

    procurement_mode: str | None
    object_applicable: bool
    status: str
    object_sector: str | None = None
    object_type: str | None = None
    object_subtype: str | None = None
    object_context: str | None = None
    application_area: str | None = None
    classification_source: str = SOURCE_UNRESOLVED
    classification_method: str = ""
    confidence: float = 0.0
    confidence_class: str = CONFIDENCE_NONE
    matched_terms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        return self.status in RESOLVED_STATUSES and bool(self.object_type)

    def axes(self) -> tuple[str, str, str | None] | None:
        if not self.resolved:
            return None
        return (self.object_sector, self.object_type, self.object_subtype)

    def as_row(self, procurement_id: Any) -> dict[str, Any]:
        """Flat storage row for crm_procurement_object_classifications."""
        return {
            "procurement_id": procurement_id,
            "procurement_mode": self.procurement_mode,
            "object_applicable": self.object_applicable,
            "object_sector": self.object_sector,
            "object_type": self.object_type,
            "object_subtype": self.object_subtype,
            "object_context": self.object_context,
            "application_area": self.application_area,
            "classification_status": self.status,
            "classification_source": self.classification_source,
            "classification_method": self.classification_method,
            "confidence": round(float(self.confidence), 4),
            "confidence_class": self.confidence_class,
            "classification_version": OBJECT_CLASSIFICATION_VERSION,
            "matched_terms": list(self.matched_terms),
        }


def _not_applicable(mode: str | None, status: str, method: str) -> ObjectClassification:
    return ObjectClassification(
        procurement_mode=mode,
        object_applicable=False,
        status=status,
        object_sector=NA,
        object_type=NA,
        object_subtype=NA,
        classification_source=SOURCE_DETERMINISTIC,
        classification_method=method,
        confidence=1.0,
        confidence_class=CONFIDENCE_HIGH,
    )


def _unresolved(mode: str | None, status: str, method: str) -> ObjectClassification:
    return ObjectClassification(
        procurement_mode=mode,
        object_applicable=False,
        status=status,
        classification_source=SOURCE_UNRESOLVED,
        classification_method=method,
        confidence=0.0,
        confidence_class=CONFIDENCE_NONE,
    )


def model_row(
    mode: str,
    *,
    status: str,
    sector: str | None = None,
    object_type: str | None = None,
    object_subtype: str | None = None,
    object_context: str | None = None,
    application_area: str | None = None,
    confidence: float = 0.0,
    method: str = "QWEN",
    matched_terms: Iterable[str] = (),
    source: str | None = None,
) -> ObjectClassification:
    """A model-produced object-layer row.

    Only the section-8 statuses are meaningful here.  DIRECT_NA / SERVICE_NA
    collapse to the N/A sentinel; every other status keeps the axes (or None)
    exactly as validated by the caller so no partially applied row is written.

    ``source`` overrides the derived provenance so an object-stage failure is
    labelled ``QWEN_OBJECT_V1`` and a mode-stage failure ``QWEN_MODE_V1``.
    """
    resolved = status in RESOLVED_STATUSES
    if status in (STATUS_DIRECT_NA, STATUS_SERVICE_NA):
        sector = object_type = object_subtype = NA
    return ObjectClassification(
        procurement_mode=mode,
        object_applicable=resolved,
        status=status,
        object_sector=sector,
        object_type=object_type,
        object_subtype=object_subtype,
        object_context=object_context,
        application_area=application_area,
        classification_source=source
        or (SOURCE_QWEN_OBJECT if resolved else SOURCE_QWEN_MODE),
        classification_method=method,
        confidence=float(confidence),
        confidence_class=CONFIDENCE_MODEL,
        matched_terms=tuple(matched_terms),
    )


def _canonical_claim(claim: Mapping[str, Any] | None) -> tuple[str, str, str | None] | None:
    """Canonical axes from a reviewed/expert claim, or None if non-canonical."""
    if not claim:
        return None
    axes = OT.normalize_object_axes(
        sector=claim.get("object_sector") or claim.get("sector"),
        object_type=claim.get("object_type"),
        object_subtype=claim.get("object_subtype") or claim.get("object_subtype"),
    )
    sector = axes[OT.OBJECT_SECTOR_FIELD]
    object_type = axes[OT.OBJECT_TYPE_FIELD]
    if not object_type or not OT.is_canonical_object_type(object_type, sector):
        return None
    return (OT.sector_of_object_type(object_type), object_type, axes[OT.OBJECT_SUBTYPE_FIELD])


def _match_rules(text: str) -> tuple[list[tuple[int, str, str, str | None, str]], list[str]]:
    """All rule hits plus the max-priority hit terms."""
    hits: list[tuple[int, str, str, str | None, str]] = []
    terms: list[str] = []
    for priority, pattern, sector, object_type, subtype in _COMPILED:
        match = pattern.search(text)
        if match:
            hits.append((priority, sector, object_type, subtype, match.group(0)))
            terms.append(match.group(0))
    return hits, terms


# Internal engineering system: pipes / wiring inside a building are part of the
# building object, not a linear utility network.  When this marker is present a
# UTILITY_NETWORKS rule is demoted to context instead of becoming an OBJECT_TYPE.
# Secondary-works marker: "с выносом сетей", "переустройство сетей", "в том
# числе ...".  A network named as a side work does not replace the main object.
_SECONDARY_WORK_RE = re.compile(r"\b(?:вынос\w*|перенос\w*|переустройств\w*|в\s+том\s+числе)\b")

_INTERNAL_SYSTEM_RE = re.compile(
    r"\b(?:систем\w*|помещени\w*|здани\w*|корпус\w*|этаж\w*|холл\w*|коридор\w*|"
    r"квартир\w*|внутри|внутренн\w*|фгбоу|гбоу|мбоу|мкоу|маоу|гпоу|гбпоу|тогбпоу|"
    r"фгбпоу|гбуз|гауз|фап|сдк|детск\w*\s+сад\w*|школ\w*)\b"
)

def _filter_network_hits(hits, text: str):
    """Demote UTILITY_NETWORKS when it is not the object-level subject.

    Two cases: an internal engineering system inside a building (pipes / wiring
    in a school) and a network named as a secondary work (с выносом сетей, в том
    числе).  In both, the non-network object keeps priority; a pure network
    procurement is unaffected.
    """
    if not hits:
        return hits
    if not any(hit[2] == "UTILITY_NETWORKS" for hit in hits):
        return hits
    transport = [hit for hit in hits if hit[2] != "UTILITY_NETWORKS"]
    internal = bool(_INTERNAL_SYSTEM_RE.search(text)) and not re.search(r"\bнаружн\w*", text)
    if internal:
        return transport
    if transport and _SECONDARY_WORK_RE.search(text):
        return transport
    return hits

def _detect_context(text: str, *, axis: str) -> str | None:
    table = _CONTEXT_COMPILED if axis == "context" else _APPLICATION_AREA_COMPILED
    for code, pattern in table:
        if pattern.search(text):
            return code
    return None


def classify_object(
    mode: str | None,
    *,
    title: Any = None,
    mode_source: Any = None,
    reviewed: Mapping[str, Any] | None = None,
    expert: Mapping[str, Any] | None = None,
) -> ObjectClassification:
    """Canonical object classification for one procurement.

    Mode gate first; a human-confirmed claim (expert / reviewed) outranks the
    deterministic text rules; deterministic rules produce a canonical code only
    from boundary-safe matches and report conflicts instead of guessing.
    """
    if mode == "DIRECT":
        method = {
            MODE_SOURCE_ACQUISITION: "MODE_DIRECT_ACQUISITION",
            MODE_SOURCE_SUBJECT_ACQUISITION: "MODE_DIRECT_SUBJECT_ACQUISITION",
        }.get(mode_source, "MODE_DIRECT")
        return _not_applicable(mode, STATUS_DIRECT_NA, method)
    if mode == "SERVICE_NO_OBJECT":
        return _not_applicable(mode, STATUS_SERVICE_NA, "MODE_SERVICE_NO_OBJECT")
    if mode is None or mode == "AMBIGUOUS":
        return _unresolved(mode, STATUS_AMBIGUOUS, "MODE_NOT_OBJECT_RESOLVED")
    if mode != "OBJECT":
        return _unresolved(mode, STATUS_AMBIGUOUS, "MODE_UNRECOGNISED")

    raw = _fold(title)
    context = _detect_context(raw, axis="context")
    application_area = _detect_context(raw, axis="area")
    text = _strip_reference_noise(raw)

    claim = _canonical_claim(expert) or _canonical_claim(reviewed)
    if expert and _canonical_claim(expert) is None:
        return _unresolved(mode, STATUS_OBJECT_NONCANONICAL, "EXPERT_CLAIM_NONCANONICAL")
    if claim is not None:
        source = SOURCE_EXPERT_CONFIRMED if _canonical_claim(expert) else SOURCE_REVIEWED_HISTORICAL
        return ObjectClassification(
            procurement_mode=mode,
            object_applicable=True,
            status=STATUS_RESOLVED_REVIEWED,
            object_sector=claim[0],
            object_type=claim[1],
            object_subtype=claim[2],
            object_context=context,
            application_area=application_area,
            classification_source=source,
            classification_method="HUMAN_CONFIRMED_CLAIM",
            confidence=1.0,
            confidence_class=CONFIDENCE_EXPERT,
        )

    if not text:
        return _unresolved(mode, STATUS_OBJECT_MISSING, "EMPTY_TITLE")

    hits, terms = _match_rules(text)
    hits = _filter_network_hits(hits, text)
    terms = [h[4] for h in hits]
    if not hits:
        return _unresolved(mode, STATUS_OBJECT_MISSING, "NO_DETERMINISTIC_MATCH")

    top = max(hit[0] for hit in hits)
    winners = {(sector, object_type) for priority, sector, object_type, _s, _t in hits if priority == top}
    if len(winners) > 1:
        return ObjectClassification(
            procurement_mode=mode,
            object_applicable=False,
            status=STATUS_OBJECT_CONFLICT,
            object_context=context,
            application_area=application_area,
            classification_source=SOURCE_UNRESOLVED,
            classification_method="CONFLICTING_RULES:p" + str(top),
            confidence=0.0,
            confidence_class=CONFIDENCE_NONE,
            matched_terms=tuple(sorted(terms)),
        )

    priority, sector, object_type, subtype, _term = next(
        hit for hit in hits if hit[0] == top
    )
    if not OT.is_canonical_object_type(object_type, sector):
        return _unresolved(mode, STATUS_OBJECT_NONCANONICAL, "RULE_TYPE_NOT_CANONICAL")
    if subtype and not OT.is_canonical_object_subtype(subtype, object_type):
        subtype = None

    return ObjectClassification(
        procurement_mode=mode,
        object_applicable=True,
        status=STATUS_RESOLVED_HIGH_CONFIDENCE,
        object_sector=OT.sector_of_object_type(object_type),
        object_type=object_type,
        object_subtype=subtype,
        object_context=context,
        application_area=application_area,
        classification_source=SOURCE_DETERMINISTIC,
        classification_method="RULE:p" + str(priority),
        confidence=1.0,
        confidence_class=CONFIDENCE_HIGH,
        matched_terms=tuple(sorted(set(terms))),
    )


def classify_from_title(mode: Any, title: Any, **kwargs: Any) -> ObjectClassification:
    """Convenience wrapper taking a raw production scope value for the mode.

    Mode resolution is title/OKPD-aware, so a dwelling purchase -- bought by
    verb or with a dwelling auction subject -- is DIRECT/N/A here even when its
    scope authority row says WORKS_WITH_EMBEDDED_PRODUCTS.
    """
    resolved, mode_source = resolve_procurement_mode_with_source(
        mode, title=title, okpd_code=kwargs.pop("okpd_code", None)
    )
    return classify_object(resolved, title=title, mode_source=mode_source, **kwargs)


def validate_classification(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Axis consistency errors for a storage row; empty tuple means valid."""
    errors: list[str] = []
    status = row.get("classification_status")
    if status not in CLASSIFICATION_STATUS_VALUES:
        errors.append(f"unknown classification_status {status!r}")
    source = row.get("classification_source")
    if source not in ALLOWED_CLASSIFICATION_SOURCES and status not in UNRESOLVED_STATUSES:
        errors.append(f"classification_source {source!r} not allowed for resolved row")
    confidence_class = row.get("confidence_class")
    if confidence_class not in (
        CONFIDENCE_EXPERT, CONFIDENCE_MODEL, CONFIDENCE_HIGH, CONFIDENCE_NONE
    ):
        errors.append(f"unknown confidence_class {confidence_class!r}")

    applicable = row.get("object_applicable")
    sector = row.get("object_sector")
    object_type = row.get("object_type")
    subtype = row.get("object_subtype")

    resolved = status in RESOLVED_STATUSES
    if resolved:
        if not applicable:
            errors.append("resolved row must have object_applicable=True")
        if not OT.is_canonical_object_type(object_type, sector):
            errors.append(f"object_type {object_type!r} invalid for sector {sector!r}")
        if subtype and not OT.is_canonical_object_subtype(subtype, object_type):
            errors.append(f"object_subtype {subtype!r} invalid for type {object_type!r}")
    elif status in (STATUS_DIRECT_NA, STATUS_SERVICE_NA):
        if applicable:
            errors.append(f"{status} must have object_applicable=False")
        if (sector, object_type, subtype) != (NA, NA, NA):
            errors.append(f"{status} axes must all be N/A")
    else:
        if applicable:
            errors.append(f"{status} must have object_applicable=False")
        if object_type not in (None, ""):
            errors.append(f"{status} must not carry an OBJECT_TYPE")
    if row.get("classification_version") != OBJECT_CLASSIFICATION_VERSION:
        errors.append("classification_version mismatch")
    return tuple(errors)


def classification_stats() -> dict[str, Any]:
    return {
        "authority": OBJECT_LAYER_AUTHORITY,
        "classification_version": OBJECT_CLASSIFICATION_VERSION,
        "table": CLASSIFICATION_TABLE,
        "rule_count": len(_COMPILED),
        "context_terms": [code for code, _ in _CONTEXT_COMPILED],
        "application_area_terms": [code for code, _ in _APPLICATION_AREA_COMPILED],
        "statuses": list(CLASSIFICATION_STATUS_VALUES),
        "allowed_sources": list(ALLOWED_CLASSIFICATION_SOURCES),
    }