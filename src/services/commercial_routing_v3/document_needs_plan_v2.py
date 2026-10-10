"""Canonical DOCUMENT_NEEDS_PLAN_V2 (read-only).

Maps a CURRENT category opportunity to:

    required facts -> document classes able to prove them -> per-file decision

It does NOT download, does not write, and does not touch the queue.
The category registry (``crm_product_categories``) stays the single taxonomy
authority: it is consumed through :func:`adapt_category_registry`, never
re-declared here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence

from .document_classifier_v1 import (
    DOCUMENT_CLASSIFIER_VERSION,
    DocumentClass,
    DocumentClassification,
)
from .research_action_v2 import GROUP_DESIGN, GROUP_DIRECT, GROUP_EMBEDDED, GROUP_UNKNOWN

DOCUMENT_NEEDS_POLICY_VERSION = "document_needs_plan_v2"
DOCUMENT_SELECTION_POLICY_VERSION = "document_selection_v2"


class RequiredFact(str, Enum):
    PRODUCT_IDENTITY = "PRODUCT_IDENTITY"
    MATERIAL_IDENTITY = "MATERIAL_IDENTITY"
    QUANTITY = "QUANTITY"
    UNIT = "UNIT"
    UNIT_PRICE = "UNIT_PRICE"
    CATEGORY_TOTAL_VALUE = "CATEGORY_TOTAL_VALUE"
    TECHNICAL_SPECIFICATION = "TECHNICAL_SPECIFICATION"
    BRAND_MODEL = "BRAND_MODEL"
    PRODUCT_CHARACTERISTICS = "PRODUCT_CHARACTERISTICS"
    DELIVERY_PERIOD = "DELIVERY_PERIOD"
    DELIVERY_LOCATION = "DELIVERY_LOCATION"
    PROJECT_SECTION = "PROJECT_SECTION"
    OBJECT_TYPE = "OBJECT_TYPE"
    WORK_VOLUME = "WORK_VOLUME"
    CONTRACT_TERM = "CONTRACT_TERM"
    PARTICIPANT_REQUIREMENT = "PARTICIPANT_REQUIREMENT"
    SECURITY_REQUIREMENT = "SECURITY_REQUIREMENT"


F = RequiredFact
C = DocumentClass

#: Which document classes are able to prove a required fact.
FACT_PROVABLE_BY: dict[RequiredFact, tuple[DocumentClass, ...]] = {
    F.PRODUCT_IDENTITY: (C.TECH_SPEC, C.PRODUCT_SPECIFICATION, C.MATERIAL_SPECIFICATION, C.BOQ, C.ESTIMATE),
    F.MATERIAL_IDENTITY: (C.MATERIAL_SPECIFICATION, C.ESTIMATE, C.BOQ, C.PROJECT_DOCUMENTATION, C.WORKING_DOCUMENTATION),
    F.QUANTITY: (C.BOQ, C.ESTIMATE, C.MATERIAL_SPECIFICATION, C.PRODUCT_SPECIFICATION, C.TECH_SPEC),
    F.UNIT: (C.BOQ, C.ESTIMATE, C.MATERIAL_SPECIFICATION, C.PRODUCT_SPECIFICATION, C.TECH_SPEC),
    F.UNIT_PRICE: (C.ESTIMATE, C.BOQ, C.NMCK_JUSTIFICATION),
    F.CATEGORY_TOTAL_VALUE: (C.ESTIMATE, C.BOQ, C.NMCK_JUSTIFICATION),
    F.TECHNICAL_SPECIFICATION: (C.TECH_SPEC, C.PRODUCT_SPECIFICATION, C.PROJECT_DOCUMENTATION),
    F.BRAND_MODEL: (C.TECH_SPEC, C.PRODUCT_SPECIFICATION),
    F.PRODUCT_CHARACTERISTICS: (C.TECH_SPEC, C.PRODUCT_SPECIFICATION, C.MATERIAL_SPECIFICATION),
    F.DELIVERY_PERIOD: (C.CONTRACT_PROJECT, C.TECH_SPEC, C.PRODUCT_SPECIFICATION),
    F.DELIVERY_LOCATION: (C.CONTRACT_PROJECT, C.TECH_SPEC),
    F.PROJECT_SECTION: (C.PROJECT_DOCUMENTATION, C.WORKING_DOCUMENTATION, C.ESTIMATE, C.BOQ),
    F.OBJECT_TYPE: (C.PROJECT_DOCUMENTATION, C.TECH_SPEC),
    F.WORK_VOLUME: (C.BOQ, C.ESTIMATE),
    F.CONTRACT_TERM: (C.CONTRACT_PROJECT,),
    F.PARTICIPANT_REQUIREMENT: (C.PARTICIPANT_REQUIREMENTS,),
    F.SECURITY_REQUIREMENT: (C.SECURITY_REQUIREMENTS,),
}

#: DIRECT_SUPPLY required facts (Phase 4). Contract/delivery facts are optional
#: for DIRECT because the procurement itself already carries them.
_DIRECT_FACTS = (
    F.PRODUCT_IDENTITY,
    F.QUANTITY,
    F.UNIT,
    F.TECHNICAL_SPECIFICATION,
    F.PRODUCT_CHARACTERISTICS,
)
_DIRECT_OPTIONAL_FACTS = (
    F.CATEGORY_TOTAL_VALUE,
    F.DELIVERY_PERIOD,
    F.DELIVERY_LOCATION,
)

#: (category_code, track_group) -> required facts. Phases 4/5 of the WIP.
CATEGORY_REQUIRED_FACTS: dict[tuple[str, str], tuple[RequiredFact, ...]] = {
    ("computers", GROUP_DIRECT): _DIRECT_FACTS + (F.BRAND_MODEL,),
    ("lighting", GROUP_DIRECT): _DIRECT_FACTS,
    ("cable_support_systems", GROUP_DIRECT): _DIRECT_FACTS,
    ("waterproofing", GROUP_EMBEDDED): (
        F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.UNIT_PRICE, F.CATEGORY_TOTAL_VALUE, F.PROJECT_SECTION,
    ),
    ("flooring", GROUP_EMBEDDED): (
        F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.UNIT_PRICE, F.CATEGORY_TOTAL_VALUE,
    ),
    ("lighting", GROUP_EMBEDDED): (
        F.PRODUCT_IDENTITY, F.QUANTITY, F.UNIT, F.TECHNICAL_SPECIFICATION, F.PROJECT_SECTION,
    ),
    ("curbstone", GROUP_EMBEDDED): (
        F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.CATEGORY_TOTAL_VALUE,
    ),
    ("composite_structures", GROUP_EMBEDDED): (
        F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.TECHNICAL_SPECIFICATION, F.CATEGORY_TOTAL_VALUE,
    ),
    ("composites", GROUP_EMBEDDED): (
        F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.TECHNICAL_SPECIFICATION, F.CATEGORY_TOTAL_VALUE,
    ),
    ("drainage_water_management", GROUP_EMBEDDED): (
        F.PRODUCT_IDENTITY, F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT,
        F.PROJECT_SECTION, F.CATEGORY_TOTAL_VALUE,
    ),
    ("cable_products", GROUP_EMBEDDED): (F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.CATEGORY_TOTAL_VALUE),
    ("structural_reinforcement", GROUP_EMBEDDED): (F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.TECHNICAL_SPECIFICATION),
    ("bridge_road_infrastructure", GROUP_EMBEDDED): (F.PRODUCT_IDENTITY, F.QUANTITY, F.UNIT, F.TECHNICAL_SPECIFICATION),
    ("external_utility_networks", GROUP_EMBEDDED): (F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.PROJECT_SECTION),
    ("concrete_materials", GROUP_EMBEDDED): (F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.CATEGORY_TOTAL_VALUE),
    ("waterproofing_concrete_repair", GROUP_EMBEDDED): (
        F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.UNIT_PRICE, F.CATEGORY_TOTAL_VALUE,
    ),
}

#: Fallbacks when a (category, track_group) pair is not declared.
FALLBACK_FACTS: dict[str, tuple[RequiredFact, ...]] = {
    GROUP_DIRECT: _DIRECT_FACTS,
    GROUP_EMBEDDED: (F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.CATEGORY_TOTAL_VALUE),
    GROUP_DESIGN: (F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT, F.PROJECT_SECTION, F.OBJECT_TYPE),
    GROUP_UNKNOWN: (F.MATERIAL_IDENTITY, F.QUANTITY, F.UNIT),
}

#: Facts whose proof is optional (documented, but a missing file is not a gap).
OPTIONAL_FACTS: dict[str, tuple[RequiredFact, ...]] = {
    GROUP_DIRECT: _DIRECT_OPTIONAL_FACTS,
    GROUP_EMBEDDED: (),
    GROUP_DESIGN: (),
    GROUP_UNKNOWN: (),
}


@dataclass(frozen=True)
class CategoryPlan:
    category_code: str
    track_group: str
    required_facts: tuple[RequiredFact, ...]
    optional_facts: tuple[RequiredFact, ...] = ()
    required_classes: tuple[DocumentClass, ...] = ()
    optional_classes: tuple[DocumentClass, ...] = ()
    provable_classes: tuple[DocumentClass, ...] = ()
    source: str = "canonical"


@dataclass(frozen=True)
class DocumentNeedsPlan:
    procurement_id: int
    category_plans: tuple[CategoryPlan, ...]
    required_facts: tuple[RequiredFact, ...]
    required_classes: tuple[DocumentClass, ...]
    optional_classes: tuple[DocumentClass, ...]
    provable_classes: tuple[DocumentClass, ...] = ()
    policy_version: str = DOCUMENT_NEEDS_POLICY_VERSION
    selection_policy_version: str = DOCUMENT_SELECTION_POLICY_VERSION
    classifier_version: str = DOCUMENT_CLASSIFIER_VERSION


@dataclass(frozen=True)
class FileSelection:
    procurement_id: int
    source_document_id: Optional[int]
    file_name: str
    document_class: DocumentClass
    classification_confidence: float
    classification_reason: str
    required_by_categories: tuple[str, ...]
    required_facts: tuple[str, ...]
    selection_decision: str
    selection_reason: str
    policy_version: str = DOCUMENT_SELECTION_POLICY_VERSION

    @property
    def http_request_potential(self) -> int:
        return 1 if self.selection_decision in (SELECTED, SELECTED_FALLBACK) else 0


SELECTED = "SELECTED"
SELECTED_FALLBACK = "SELECTED_FALLBACK"
SKIPPED_NOT_RELEVANT = "SKIPPED_NOT_RELEVANT"
UNKNOWN_NEEDS_REVIEW = "UNKNOWN_NEEDS_REVIEW"

#: Fallback classes that are normally NOT requested, ordered by their measured
#: contribution to historical positive recall (document_matches audit 2026-10-10).
#: Used ONLY when a (procurement, category) unit has no accepted-class document.
FALLBACK_CLASS_PRIORITY: tuple[DocumentClass, ...] = (
    DocumentClass.CONTRACT_PROJECT,
    DocumentClass.PARTICIPANT_REQUIREMENTS,
    DocumentClass.NMCK_JUSTIFICATION,
    DocumentClass.LEGAL_GENERAL,
    DocumentClass.SECURITY_REQUIREMENTS,
    DocumentClass.OTHER,
)
FALLBACK_MAX_PER_UNIT = 1


def _fallback_rank(classification: DocumentClassification) -> int:
    """Lower is better; non-documents are the very last resort."""
    if not classification.is_document:
        return len(FALLBACK_CLASS_PRIORITY) + 2
    if classification.document_class in FALLBACK_CLASS_PRIORITY:
        return FALLBACK_CLASS_PRIORITY.index(classification.document_class)
    return len(FALLBACK_CLASS_PRIORITY) + 1


def classes_for_facts(facts: Iterable[RequiredFact]) -> tuple[DocumentClass, ...]:
    ordered: list[DocumentClass] = []
    for fact in facts:
        for doc_class in FACT_PROVABLE_BY.get(fact, ()):
            if doc_class not in ordered:
                ordered.append(doc_class)
    return tuple(ordered)


ACCEPTED_DIRECT: tuple[DocumentClass, ...] = (
    C.TECH_SPEC,
    C.PRODUCT_SPECIFICATION,
    C.MATERIAL_SPECIFICATION,
)
ACCEPTED_EMBEDDED: tuple[DocumentClass, ...] = (
    C.ESTIMATE,
    C.BOQ,
    C.MATERIAL_SPECIFICATION,
    C.PROJECT_DOCUMENTATION,
    C.WORKING_DOCUMENTATION,
    C.TECH_SPEC,
    C.PRODUCT_SPECIFICATION,
)

#: Category-aware document policy: which classes are worth an HTTP request
#: for this (category, track) - Phases 4/5 of the WIP.
CATEGORY_ACCEPTED_CLASSES: dict[tuple[str, str], tuple[DocumentClass, ...]] = {
    ("computers", GROUP_DIRECT): (C.TECH_SPEC, C.PRODUCT_SPECIFICATION),
    ("lighting", GROUP_DIRECT): (C.TECH_SPEC, C.PRODUCT_SPECIFICATION),
    ("cable_support_systems", GROUP_DIRECT): (C.TECH_SPEC, C.PRODUCT_SPECIFICATION),
    ("lighting", GROUP_EMBEDDED): (
        C.TECH_SPEC, C.PRODUCT_SPECIFICATION, C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION,
        C.PROJECT_DOCUMENTATION,
    ),
    ("waterproofing", GROUP_EMBEDDED): (
        C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION, C.PROJECT_DOCUMENTATION, C.WORKING_DOCUMENTATION,
    ),
    ("flooring", GROUP_EMBEDDED): (
        C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION, C.PROJECT_DOCUMENTATION, C.WORKING_DOCUMENTATION,
    ),
}
ACCEPTED_OPTIONAL: dict[str, tuple[DocumentClass, ...]] = {
    GROUP_DIRECT: (C.NMCK_JUSTIFICATION, C.CONTRACT_PROJECT),
    GROUP_EMBEDDED: (),
    GROUP_DESIGN: (),
    GROUP_UNKNOWN: (),
}
ACCEPTED_FALLBACK: dict[str, tuple[DocumentClass, ...]] = {
    GROUP_DIRECT: ACCEPTED_DIRECT,
    GROUP_EMBEDDED: ACCEPTED_EMBEDDED,
    GROUP_DESIGN: (C.PROJECT_DOCUMENTATION, C.WORKING_DOCUMENTATION, C.TECH_SPEC),
    GROUP_UNKNOWN: ACCEPTED_EMBEDDED,
}


def category_plan(category_code: str, group: str) -> CategoryPlan:
    facts = CATEGORY_REQUIRED_FACTS.get((category_code, group))
    source = "canonical"
    if facts is None:
        facts = FALLBACK_FACTS.get(group, FALLBACK_FACTS[GROUP_UNKNOWN])
        source = "fallback"
    optional = OPTIONAL_FACTS.get(group, ())
    accepted = CATEGORY_ACCEPTED_CLASSES.get((category_code, group)) or ACCEPTED_FALLBACK.get(group, ())
    provable = classes_for_facts(facts)
    required_classes = tuple(dict.fromkeys(c for c in accepted if c in provable))
    accepted_optional = ACCEPTED_OPTIONAL.get(group, ())
    optional_classes = tuple(
        c for c in accepted_optional if c not in required_classes
    ) + tuple(c for c in accepted if c in classes_for_facts(optional) and c not in required_classes)
    return CategoryPlan(
        category_code=category_code,
        track_group=group,
        required_facts=tuple(facts),
        optional_facts=tuple(optional),
        required_classes=required_classes,
        optional_classes=optional_classes,
        provable_classes=provable,
        source=source,
    )


def build_document_needs_plan(
    procurement_id: int, plans: Sequence[CategoryPlan]
) -> DocumentNeedsPlan:
    """Union of per-category needs (multi-category procurement = one plan)."""
    facts: list[RequiredFact] = []
    required: list[DocumentClass] = []
    optional: list[DocumentClass] = []
    provable: list[DocumentClass] = []
    for plan in plans:
        for fact in plan.required_facts:
            if fact not in facts:
                facts.append(fact)
        for doc_class in plan.required_classes:
            if doc_class not in required:
                required.append(doc_class)
        for doc_class in plan.optional_classes:
            if doc_class not in required and doc_class not in optional:
                optional.append(doc_class)
        for doc_class in plan.provable_classes:
            if doc_class not in provable:
                provable.append(doc_class)
    return DocumentNeedsPlan(
        procurement_id=procurement_id,
        category_plans=tuple(plans),
        required_facts=tuple(facts),
        required_classes=tuple(required),
        optional_classes=tuple(optional),
        provable_classes=tuple(provable),
    )


def decide_file_selection(
    plan: DocumentNeedsPlan,
    classification: DocumentClassification,
    *,
    procurement_id: int,
    source_document_id: Optional[int] = None,
    file_name: str = "",
    item_category: Optional[str] = None,
) -> FileSelection:
    """Pre-HTTP decision. SELECTED is only reachable for a provable fact."""
    doc_class = classification.document_class
    required_by = tuple(
        p.category_code
        for p in plan.category_plans
        if doc_class in p.required_classes and (item_category is None or p.category_code == item_category)
    )
    facts = tuple(
        sorted(
            {
                fact.value
                for p in plan.category_plans
                for fact in p.required_facts
                if doc_class in FACT_PROVABLE_BY.get(fact, ())
                and (item_category is None or p.category_code == item_category)
            }
        )
    )
    if not classification.is_document:
        decision, reason = SKIPPED_NOT_RELEVANT, f"NON_DOCUMENT:{classification.reason}"
    elif doc_class == C.OTHER:
        # Unclassified document: never deleted automatically (Phase 10).
        decision, reason = UNKNOWN_NEEDS_REVIEW, f"UNCLASSIFIED_DOCUMENT:{classification.reason}"
    elif doc_class in plan.required_classes and required_by:
        decision, reason = SELECTED, f"PROVES_REQUIRED_FACTS:{','.join(facts) or 'NONE'}"
    elif doc_class in plan.optional_classes:
        decision, reason = SKIPPED_NOT_RELEVANT, "OPTIONAL_CLASS_NOT_REQUIRED"
    elif doc_class in plan.provable_classes:
        decision, reason = SKIPPED_NOT_RELEVANT, "CLASS_NOT_ACCEPTED_FOR_CATEGORY"
    else:
        decision, reason = SKIPPED_NOT_RELEVANT, "CLASS_CANNOT_PROVE_ANY_REQUIRED_FACT"
    return FileSelection(
        procurement_id=procurement_id,
        source_document_id=source_document_id,
        file_name=file_name,
        document_class=doc_class,
        classification_confidence=classification.confidence,
        classification_reason=classification.reason,
        required_by_categories=required_by,
        required_facts=facts,
        selection_decision=decision,
        selection_reason=reason,
    )


def select_unit_documents(
    plan: DocumentNeedsPlan,
    *,
    procurement_id: int,
    category_code: str,
    documents: Sequence[tuple[Optional[int], str, DocumentClassification]],
) -> tuple[list[FileSelection], Optional[FileSelection]]:
    """Recall-safe selection for ONE (procurement, category) unit.

    Layer on top of :func:`decide_file_selection` (unchanged V1 semantics):
    if the unit has no accepted-class document at all, exactly ONE fallback
    document is promoted to SELECTED_FALLBACK. Classes and facts are untouched.
    """
    pairs = [
        (
            classification,
            decide_file_selection(
                plan,
                classification,
                procurement_id=procurement_id,
                source_document_id=source_document_id,
                file_name=file_name,
                item_category=category_code,
            ),
        )
        for source_document_id, file_name, classification in documents
    ]
    if any(selection.selection_decision == SELECTED for _, selection in pairs):
        return [selection for _, selection in pairs], None
    if not pairs:
        return [], None

    order = sorted(
        range(len(pairs)),
        key=lambda i: (
            _fallback_rank(pairs[i][0]),
            pairs[i][1].source_document_id if pairs[i][1].source_document_id is not None else 1 << 62,
            pairs[i][1].file_name.lower(),
        ),
    )
    promoted_index = order[0]
    classification, selection = pairs[promoted_index]
    promoted = FileSelection(
        procurement_id=procurement_id,
        source_document_id=selection.source_document_id,
        file_name=selection.file_name,
        document_class=classification.document_class,
        classification_confidence=classification.confidence,
        classification_reason=classification.reason,
        required_by_categories=(category_code,),
        required_facts=(),
        selection_decision=SELECTED_FALLBACK,
        selection_reason=f"FALLBACK_NO_ACCEPTED_DOC:{classification.document_class.value}",
    )
    pairs[promoted_index] = (classification, promoted)
    return [item for _, item in pairs], promoted


def http_request_potential(selections: Iterable[FileSelection]) -> int:
    """Selected documents only (accepted + fallback promotions)."""
    return sum(
        1 for s in selections if s.selection_decision in (SELECTED, SELECTED_FALLBACK)
    )


# ---------------------------------------------------------------- registry adapter

#: registry extraction field -> canonical required facts
EXTRACTION_FIELD_TO_FACTS: dict[str, tuple[RequiredFact, ...]] = {
    "product_name": (F.PRODUCT_IDENTITY,),
    "material_type": (F.MATERIAL_IDENTITY,),
    "model": (F.BRAND_MODEL, F.PRODUCT_CHARACTERISTICS),
    "mark": (F.BRAND_MODEL,),
    "grade": (F.PRODUCT_CHARACTERISTICS,),
    "dimensions": (F.PRODUCT_CHARACTERISTICS,),
    "diameter_mm": (F.PRODUCT_CHARACTERISTICS,),
    "thickness_mm": (F.PRODUCT_CHARACTERISTICS,),
    "power_w": (F.PRODUCT_CHARACTERISTICS,),
    "load_class": (F.PRODUCT_CHARACTERISTICS,),
    "application_type": (F.PRODUCT_CHARACTERISTICS,),
    "quantity": (F.QUANTITY,),
    "unit": (F.UNIT,),
    "unit_price": (F.UNIT_PRICE,),
    "total_price": (F.CATEGORY_TOTAL_VALUE,),
}

#: registry section-plan keywords -> document classes
SECTION_KEYWORD_TO_CLASSES: tuple[tuple[str, tuple[DocumentClass, ...]], ...] = (
    ("смет", (C.ESTIMATE,)),
    ("ведомост", (C.BOQ, C.MATERIAL_SPECIFICATION)),
    ("спецификац", (C.PRODUCT_SPECIFICATION, C.MATERIAL_SPECIFICATION)),
    ("техническое задание", (C.TECH_SPEC,)),
    ("проект", (C.PROJECT_DOCUMENTATION,)),
    ("рабоч", (C.WORKING_DOCUMENTATION,)),
    ("оборудован", (C.PRODUCT_SPECIFICATION,)),
    # category-domain section names -> where such a section actually lives
    ("гидроизоляц", (C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION)),
    ("кровл", (C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION)),
    ("дренаж", (C.ESTIMATE, C.BOQ, C.PROJECT_DOCUMENTATION)),
    ("водоотвод", (C.ESTIMATE, C.BOQ, C.PROJECT_DOCUMENTATION)),
    ("лоток", (C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION)),
    ("бордюр", (C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION)),
    ("материал", (C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION)),
    ("арматур", (C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION)),
    ("настил", (C.PROJECT_DOCUMENTATION, C.MATERIAL_SPECIFICATION)),
    ("огражден", (C.PROJECT_DOCUMENTATION, C.MATERIAL_SPECIFICATION)),
    ("опорн", (C.PROJECT_DOCUMENTATION,)),
    ("шов", (C.PROJECT_DOCUMENTATION,)),
    ("кабельн", (C.PRODUCT_SPECIFICATION, C.PROJECT_DOCUMENTATION)),
    ("электроснабжен", (C.PRODUCT_SPECIFICATION, C.PROJECT_DOCUMENTATION)),
    ("инженерные сети", (C.PROJECT_DOCUMENTATION,)),
    ("трубопровод", (C.PROJECT_DOCUMENTATION,)),
    ("бетон", (C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION)),
    ("освещени", (C.ESTIMATE, C.BOQ, C.PRODUCT_SPECIFICATION)),
    ("благоустройств", (C.ESTIMATE, C.BOQ, C.PROJECT_DOCUMENTATION)),
    ("покрыти", (C.ESTIMATE, C.BOQ, C.MATERIAL_SPECIFICATION)),
    ("усилени", (C.PROJECT_DOCUMENTATION, C.MATERIAL_SPECIFICATION)),
    ("ремонт", (C.ESTIMATE, C.PROJECT_DOCUMENTATION)),
)


@dataclass
class RegistryAdapterReport:
    registry_rows: int = 0
    mapped_to_v2: int = 0
    unmapped: list = field(default_factory=list)
    ambiguous: list = field(default_factory=list)
    field_hits: dict = field(default_factory=dict)
    section_class_hits: dict = field(default_factory=dict)


def adapt_category_registry(rows: Sequence[dict]) -> tuple[dict[str, CategoryPlan], RegistryAdapterReport]:
    """Adapter: existing category registry -> canonical facts / document classes.

    Produces an advisory per-category plan derived from ``extraction_fields``
    and ``section_search_plan``. It never replaces the canonical facts above;
    it is used to prove the registry covers the same needs.
    """
    report = RegistryAdapterReport()
    adapted: dict[str, CategoryPlan] = {}
    for row in rows:
        report.registry_rows += 1
        code = row.get("category_code") or ""
        facts: list[RequiredFact] = []
        for item in row.get("extraction_fields") or []:
            name = (item.get("field") if isinstance(item, dict) else str(item)) or ""
            mapped = EXTRACTION_FIELD_TO_FACTS.get(name)
            report.field_hits[name] = report.field_hits.get(name, 0) + 1
            if not mapped:
                report.unmapped.append((code, f"extraction_field:{name}"))
                continue
            if len(mapped) > 1:
                report.ambiguous.append((code, f"extraction_field:{name}"))
            for fact in mapped:
                if fact not in facts:
                    facts.append(fact)
        classes: list[DocumentClass] = []
        for step in row.get("document_search_plan") or []:
            text = f"{step.get('target', '')} {' '.join(step.get('keywords') or [])}".lower() \
                if isinstance(step, dict) else str(step).lower()
            hit = False
            for keyword, mapped_classes in SECTION_KEYWORD_TO_CLASSES:
                if keyword in text:
                    hit = True
                    report.section_class_hits[keyword] = report.section_class_hits.get(keyword, 0) + 1
                    for doc_class in mapped_classes:
                        if doc_class not in classes:
                            classes.append(doc_class)
            if not hit and text.strip():
                report.unmapped.append((code, f"section_step:{text[:40]}"))
        if facts or classes:
            report.mapped_to_v2 += 1
        adapted[code] = CategoryPlan(
            category_code=code,
            track_group=row.get("default_role") or "",
            required_facts=tuple(facts),
            required_classes=tuple(classes),
            source="registry_adapter",
        )
    return adapted, report
