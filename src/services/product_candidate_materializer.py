"""Layer 1 materialization contract: PROCUREMENT_MODE -> OBJECT -> PRODUCT candidates.

This module is the persistence-facing sibling of
``src/services/object_product_applicability.py``.  The matrix module answers
"on this object, which products make sense to look for".  This module answers
the narrower production question: "for which procurements is that answer
allowed to be written to crm_procurement_product_candidates at all".

Two hard rules live here.

1. PROCUREMENT MODE GATE (checked first, before any object or product work):
   only ``OBJECT`` procurements may produce embedded-product candidates.
   DIRECT / SERVICE_NO_OBJECT / AMBIGUOUS / unknown-mode -> no candidates.

2. OBJECT SOURCE POLICY (WIP PRODUCT-CANDIDATE-LAYER-PRODUCTION-V1 section 5):
   a free-text object label is never truth on its own.  A canonical object is
   accepted only when it comes from an allowed source AND still passes
   ``expert_object_taxonomy`` canonical validation.  Regex/substring text
   discovery may FIND a candidate object elsewhere, but it may not CONFIRM one,
   so it is deliberately absent from the allow-list.

A candidate is not an opportunity and not a medal: Layer 1 writes
``candidate_status=PRE_EVIDENCE`` rows and nothing else.

A title-level override sits in front of the scope lookup: buying a finished
dwelling (приобретение / покупка / выкуп of a квартира or жилое помещение) is a
DIRECT goods purchase no matter what the scope authority says, so it can never
materialize embedded-product candidates
(WIP=DWELLING-PURCHASE-DIRECT-REMEDIATION-V1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.services import expert_object_taxonomy as _OT
from src.services import object_product_applicability as _OPA
from src.services import product_ontology as _PO

CANDIDATE_MODEL_VERSION = _OPA.CANDIDATE_MODEL_VERSION
CANDIDATE_SOURCE = "OBJECT_PRODUCT_MATRIX"
CANDIDATE_STATUS = _OPA.CANDIDATE_STATUS_PRE_EVIDENCE
MATERIALIZER_AUTHORITY = "src/services/product_candidate_materializer.py"

# Section 5.  Only these provenance labels may confirm a canonical object.
# QWEN_OBJECT_V1 was added by WIP=MASS-CANONICAL-OBJECT-LAYER-RUN-V1 section 8:
# a model result may confirm an object ONLY after strict canonical validation
# (object_classification / qwen_object_classifier).  Free-text model output is
# still refused below by FORBIDDEN_OBJECT_SOURCE_PREFIXES.
ALLOWED_OBJECT_SOURCES = (
    "REVIEWED",
    "EXPERT_CONFIRMED",
    "CANONICAL_CURRENT",
    "DETERMINISTIC_HIGH_CONFIDENCE",
    "QWEN_OBJECT_V1",
)

# section 11 of the preceding WIP: regex/substring discovery is candidate-only.
FORBIDDEN_OBJECT_SOURCE_PREFIXES = ("REGEX", "SUBSTRING", "AI_FREETEXT", "LEGACY_FREETEXT")

# Object sources that resolved only the procurement MODE; they never confirm an
# object and must stay out of ALLOWED_OBJECT_SOURCES.
MODE_ONLY_SOURCES = ("QWEN_MODE_V1",)

MODE_SOURCE_SCOPE_AUTHORITY = "crm_procurement_scope_authority.procurement_scope_type"
MODE_SOURCE_ACQUISITION = "TITLE_DWELLING_ACQUISITION"
MODE_SOURCE_SUBJECT_ACQUISITION = "TITLE_DWELLING_SUBJECT_ACQUISITION"

# --- dwelling acquisition -> DIRECT (WIP=DWELLING-PURCHASE-DIRECT-REMEDIATION-V1)
# Buying a finished dwelling is a DIRECT goods purchase, so both the object layer
# and Layer 1 stay OFF for it (contract: "приобретение квартиры -> DIRECT").
# The detector is deliberately narrow so that construction / repair / design of
# housing and equipment purchases are NOT demoted to DIRECT:
#   * the acquisition verb must sit OUTSIDE every parenthetical aside, which
#     rejects "(включая приобретение приборов учета)";
#   * the dwelling noun must follow the verb within a short window, so a distant
#     mention cannot fire;
#   * the dwelling noun needs a LEFT word boundary, so "многоквартирных" and
#     "нежилого помещения" do not count as "квартира" / "жилое помещение".
ACQUISITION_ARE_DIRECT = True
DWELLING_ACQUISITION_WINDOW = 130

_FOLD_WS = re.compile(r"\s+")
_PARENTHETICAL = re.compile(r"\([^)]*\)")
_DWELLING_ACQ_VERB = re.compile(r"(?:приобретени|покупк|выкуп)\w*")
_DWELLING_TERM = re.compile(
    r"(?:(?<![а-яёa-z])квартир\w*"
    r"|(?<![а-яёa-z])жил(?:ое|ого|ому|ым|ом|ых|ой|ые|ая|ыми)\s+помещени\w*)"
)


def _fold_title(text: Any) -> str:
    """Lowercase, fold ё and collapse whitespace (tokens are never dropped)."""
    value = str(text or "").lower().replace("ё", "е")
    return _FOLD_WS.sub(" ", value).strip()


def is_dwelling_acquisition(title: Any) -> bool:
    """True when the procurement buys finished dwelling space (not builds it).

    Boundary-safe and aside-aware; see the rule comment above.  An empty or
    non-string title safely returns False.
    """
    folded = _fold_title(title)
    if not folded:
        return False
    spans = [(m.start(), m.end()) for m in _PARENTHETICAL.finditer(folded)]
    for verb in _DWELLING_ACQ_VERB.finditer(folded):
        if any(start <= verb.start() < end for start, end in spans):
            continue
        window = folded[verb.end(): verb.end() + DWELLING_ACQUISITION_WINDOW]
        if _DWELLING_TERM.search(window):
            return True
    return False


# --- dwelling acquisition by auction SUBJECT (DWELLING_ACQUISITION_BY_SUBJECT)
# Narrow second path for procurements whose SUBJECT is a finished dwelling
# even though no acquisition verb is present, e.g.
#   "Квартира в многоквартирном жилом доме, расположенном в г. Барыш ...".
# Conditions, all required:
#   1. OKPD is a finished-dwelling goods class (41.20.10.*; the coarse
#      ancestor 41.2 / 41.20 is accepted ONLY with programme context, because
#      it covers construction works as well);
#   2. the title names a dwelling subject (квартира / жилое помещение);
#   3. no works marker introduces that subject: the text BEFORE the first
#      dwelling-subject mention must not contain строительство, реконструкция,
#      ремонт, проектирование, благоустройство, выполнение работ, устройство,
#      монтаж.  Programme boilerplate AFTER the subject (quoted programme names,
#      "аварийными и подлежащими сносу или реконструкции") does not turn a
#      purchase into works;
#   4. for the coarse OKPD only: programme context (переселение, расселение,
#      обеспечение жильём, предоставление жилого помещения, приобретение в
#      собственность, доступность жилья).
DWELLING_GOODS_OKPD_PREFIXES = ("41.20.10",)
DWELLING_GOODS_OKPD_COARSE = ("41.2", "41.20")

_DWELLING_SUBJECT = re.compile(
    r"(?<![а-яёa-z])(?:квартир\w*"
    r"|жил(?:ое|ого|ому|ым|ом|ых|ой|ые|ая|ыми)\s+помещени\w*)"
)
_WORKS_MARKER = re.compile(
    r"строительств\w*|реконструкц\w*|ремонт\w*|проектиров\w*|благоустройств\w*"
    r"|монтаж\w*|устройств\w*|выполнени\w*\s+работ\w*"
)
_PROGRAM_CONTEXT = re.compile(
    r"переселен\w*|расселен\w*|обеспечени\w*\s+жил\w*|жилищн\w*\s+обеспечени\w*"
    r"|предоставлени\w*\s+жил\w*|приобретени\w*\s+в\s+собственност\w*"
    r"|доступност\w*\s+жил\w*"
)


def is_dwelling_acquisition_by_subject(title: Any, okpd_code: Any = None) -> bool:
    """True when the auction SUBJECT itself is finished dwelling space.

    Path for procurements that name a dwelling as the subject without an
    acquisition verb (e.g. "Квартира в многоквартирном жилом доме, ...").
    All four conditions must hold: a finished-dwelling OKPD class, a dwelling
    subject noun, no works marker BEFORE that noun, and -- for the coarse OKPD
    ancestor only -- programme context.
    """
    folded = _fold_title(title)
    okpd = _FOLD_WS.sub("", str(okpd_code or "")).strip()
    if not folded or not okpd:
        return False
    if okpd.startswith(DWELLING_GOODS_OKPD_PREFIXES):
        need_context = False
    elif okpd in DWELLING_GOODS_OKPD_COARSE:
        need_context = True
    else:
        return False
    subject = _DWELLING_SUBJECT.search(folded)
    if subject is None:
        return False
    if _WORKS_MARKER.search(folded[: subject.start()]):
        return False
    if need_context and _PROGRAM_CONTEXT.search(folded) is None:
        return False
    return True


# Production scope vocabulary -> canonical PROCUREMENT_MODE.  Anything absent
# (including UNKNOWN) maps to None, which is reported as UNKNOWN_MODE.
SCOPE_TYPE_TO_MODE: Mapping[str, str] = {
    "DIRECT_GOODS": _PO.PROCUREMENT_MODE_DIRECT,
    "WORKS_WITH_EMBEDDED_PRODUCTS": _PO.PROCUREMENT_MODE_OBJECT,
    "PURE_SERVICE": _PO.PROCUREMENT_MODE_SERVICE_NO_OBJECT,
    "SERVICE_WITH_CONSUMABLES": _PO.PROCUREMENT_MODE_SERVICE_NO_OBJECT,
    "DESIGN_PROJECT": _PO.PROCUREMENT_MODE_AMBIGUOUS,
    "EQUIPMENT_AND_INSTALLATION": _PO.PROCUREMENT_MODE_AMBIGUOUS,
    "MIXED": _PO.PROCUREMENT_MODE_AMBIGUOUS,
}

OBJECT_STATUS_RESOLVED = "RESOLVED"
OBJECT_STATUS_MISSING = "MISSING"
OBJECT_STATUS_UNRESOLVED = "UNRESOLVED"
OBJECT_STATUS_NONCANONICAL = "NONCANONICAL"
OBJECT_STATUS_INVALID = "INVALID"
OBJECT_STATUS_VALUES = (
    OBJECT_STATUS_RESOLVED,
    OBJECT_STATUS_MISSING,
    OBJECT_STATUS_UNRESOLVED,
    OBJECT_STATUS_NONCANONICAL,
    OBJECT_STATUS_INVALID,
)

SKIP_DIRECT = "DIRECT"
SKIP_SERVICE_NO_OBJECT = "SERVICE_NO_OBJECT"
SKIP_AMBIGUOUS_MODE = "AMBIGUOUS_MODE"
SKIP_UNKNOWN_MODE = "UNKNOWN_MODE"
SKIP_OBJECT_MISSING = "OBJECT_MISSING"
SKIP_OBJECT_NONCANONICAL = "OBJECT_NONCANONICAL"
SKIP_OBJECT_UNRESOLVED = "OBJECT_UNRESOLVED"
SKIP_OTHER = "OTHER"
SKIP_REASONS = (
    SKIP_DIRECT,
    SKIP_SERVICE_NO_OBJECT,
    SKIP_AMBIGUOUS_MODE,
    SKIP_UNKNOWN_MODE,
    SKIP_OBJECT_MISSING,
    SKIP_OBJECT_NONCANONICAL,
    SKIP_OBJECT_UNRESOLVED,
    SKIP_OTHER,
)

MATERIALIZABLE_APPLICABILITY = (_PO.APPLICABILITY_YES, _PO.APPLICABILITY_CONDITIONAL)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _norm_upper(value: Any) -> str:
    return _norm(value).upper()


def resolve_procurement_mode(
    scope_type: Any, *, title: Any = None, okpd_code: Any = None
) -> str | None:
    """Canonical mode for a production scope_type, or None (UNKNOWN_MODE).

    ``title`` / ``okpd_code`` are optional for backwards compatibility.  When a
    finished dwelling is bought by verb (``is_dwelling_acquisition``) or the
    auction subject IS a dwelling (``is_dwelling_acquisition_by_subject``),
    DIRECT wins over the scope authority table.
    """
    return resolve_procurement_mode_with_source(
        scope_type, title=title, okpd_code=okpd_code
    )[0]


def resolve_procurement_mode_with_source(
    scope_type: Any, *, title: Any = None, okpd_code: Any = None
) -> tuple[str | None, str]:
    """(mode, source) so the dwelling override stays auditable in storage."""
    if title is not None and is_dwelling_acquisition(title):
        return _PO.PROCUREMENT_MODE_DIRECT, MODE_SOURCE_ACQUISITION
    if title is not None and is_dwelling_acquisition_by_subject(title, okpd_code):
        return _PO.PROCUREMENT_MODE_DIRECT, MODE_SOURCE_SUBJECT_ACQUISITION
    return SCOPE_TYPE_TO_MODE.get(_norm_upper(scope_type)), MODE_SOURCE_SCOPE_AUTHORITY


def object_source_allowed(source: Any) -> bool:
    return _norm_upper(source) in ALLOWED_OBJECT_SOURCES


@dataclass(frozen=True, slots=True)
class ObjectSignal:
    """An object claim about one procurement, with its provenance label."""

    procurement_id: Any
    source: str
    object_sector: Any = None
    object_type: Any = None
    object_subtype: Any = None
    object_context: Any = None


@dataclass(frozen=True, slots=True)
class ObjectAssessment:
    status: str
    reason: str
    axes: tuple[str, str, str | None] | None = None


def assess_object(signal: ObjectSignal | None) -> ObjectAssessment:
    """Validate an object claim against the canonical taxonomy + source policy."""
    if signal is None:
        return ObjectAssessment(OBJECT_STATUS_MISSING, "no canonical object signal")
    if not object_source_allowed(signal.source):
        return ObjectAssessment(
            OBJECT_STATUS_NONCANONICAL,
            f"object source {_norm(signal.source)!r} is not in ALLOWED_OBJECT_SOURCES",
        )
    if not _norm(signal.object_type):
        return ObjectAssessment(OBJECT_STATUS_MISSING, "object signal carries no OBJECT_TYPE")
    axes = _OPA.resolve_object(signal.object_sector, signal.object_type, signal.object_subtype)
    if axes is None:
        if _OT.is_canonical_object_type(_norm_upper(signal.object_type)):
            return ObjectAssessment(
                OBJECT_STATUS_UNRESOLVED, "canonical OBJECT_TYPE but sector/subtype mismatch"
            )
        return ObjectAssessment(
            OBJECT_STATUS_NONCANONICAL, "OBJECT_TYPE does not resolve to a canonical code"
        )
    return ObjectAssessment(OBJECT_STATUS_RESOLVED, "canonical object resolved", axes)


def candidate_eligibility(mode: Any, object_status: str) -> tuple[bool, str | None]:
    """Gate order: procurement mode first, then canonical object."""
    canonical_mode = _norm_upper(mode)
    if canonical_mode not in _PO.PROCUREMENT_MODE_VALUES:
        return False, SKIP_UNKNOWN_MODE
    if canonical_mode == _PO.PROCUREMENT_MODE_DIRECT:
        return False, SKIP_DIRECT
    if canonical_mode == _PO.PROCUREMENT_MODE_SERVICE_NO_OBJECT:
        return False, SKIP_SERVICE_NO_OBJECT
    if canonical_mode == _PO.PROCUREMENT_MODE_AMBIGUOUS:
        return False, SKIP_AMBIGUOUS_MODE
    if object_status == OBJECT_STATUS_RESOLVED:
        return True, None
    if object_status == OBJECT_STATUS_MISSING:
        return False, SKIP_OBJECT_MISSING
    if object_status == OBJECT_STATUS_UNRESOLVED:
        return False, SKIP_OBJECT_UNRESOLVED
    if object_status in (OBJECT_STATUS_NONCANONICAL, OBJECT_STATUS_INVALID):
        return False, SKIP_OBJECT_NONCANONICAL
    return False, SKIP_OTHER


def build_candidates(
    mode: Any,
    signal: ObjectSignal | None = None,
    *,
    object_context: Any = None,
    model_version: str = CANDIDATE_MODEL_VERSION,
) -> list[dict[str, Any]]:
    """PRE_EVIDENCE candidate rows for one procurement; [] when not eligible.

    Only YES / CONDITIONAL relations are materialized.  UNKNOWN stays a
    diagnostic and NO is never generated, so ``object_product_applicability``
    is called with ``include_unknown=False``.
    """
    assessment = assess_object(signal)
    eligible, _ = candidate_eligibility(mode, assessment.status)
    if not eligible or assessment.axes is None:
        return []
    sector, object_type, object_subtype = assessment.axes
    context = object_context if object_context is not None else (signal.object_context if signal else None)
    candidates = _OPA.generate_candidates(
        mode,
        object_sector=sector,
        object_type=object_type,
        object_subtype=object_subtype,
        object_context=context,
        crm_id=signal.procurement_id if signal else None,
        include_unknown=False,
        model_version=model_version,
    )
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("APPLICABILITY") not in MATERIALIZABLE_APPLICABILITY:
            continue
        rows.append(
            {
                "PROCUREMENT_ID": signal.procurement_id if signal else None,
                "PROCUREMENT_MODE": candidate["PROCUREMENT_MODE"],
                "OBJECT_SECTOR": candidate["OBJECT_SECTOR"],
                "OBJECT_TYPE": candidate["OBJECT_TYPE"],
                "OBJECT_SUBTYPE": candidate["OBJECT_SUBTYPE"],
                "OBJECT_CONTEXT": candidate["OBJECT_CONTEXT"],
                "PRODUCT_FAMILY": candidate["PRODUCT_FAMILY"],
                "PRODUCT_TYPE": candidate["PRODUCT_TYPE"],
                "APPLICATION": candidate["APPLICATION"],
                "MATERIAL": candidate["MATERIAL"],
                "VARIANT": candidate["VARIANT"],
                "TECHNOLOGY": None,
                "APPLICABILITY": candidate["APPLICABILITY"],
                "CANDIDATE_STATUS": CANDIDATE_STATUS,
                "CANDIDATE_SOURCE": CANDIDATE_SOURCE,
                "CANDIDATE_VERSION": model_version,
                "RELATION_SOURCE": candidate["SOURCE"],
                "REASON": candidate["REASON"],
            }
        )
    return rows


def candidate_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Idempotency key, matching uix_cppc_identity in the migration."""
    return (
        row.get("PROCUREMENT_ID"),
        row.get("CANDIDATE_VERSION") or CANDIDATE_MODEL_VERSION,
        row.get("PRODUCT_FAMILY"),
        row.get("PRODUCT_TYPE"),
        row.get("APPLICATION"),
        row.get("MATERIAL"),
        row.get("VARIANT"),
        row.get("OBJECT_SECTOR"),
        row.get("OBJECT_TYPE"),
        row.get("OBJECT_SUBTYPE"),
    )


def dedupe_candidates(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated identities; the DB unique index is the second guard."""
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = candidate_identity(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def verify_invariants(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Violations of the Layer 1 write contract; empty means safe to write."""
    problems: list[str] = []
    identities: set[tuple[Any, ...]] = set()
    for row in rows:
        mode = _norm_upper(row.get("PROCUREMENT_MODE"))
        tag = f"{row.get('PROCUREMENT_ID')}/{row.get('PRODUCT_TYPE')}"
        if mode != _PO.PROCUREMENT_MODE_OBJECT:
            problems.append(f"{tag}: candidate generated outside OBJECT mode ({mode!r})")
        applicability = _norm_upper(row.get("APPLICABILITY"))
        if applicability not in MATERIALIZABLE_APPLICABILITY:
            problems.append(f"{tag}: non-materializable APPLICABILITY {applicability!r}")
        if row.get("CANDIDATE_STATUS") != CANDIDATE_STATUS:
            problems.append(f"{tag}: candidate_status must be {CANDIDATE_STATUS}")
        if row.get("TECHNOLOGY"):
            problems.append(f"{tag}: TECHNOLOGY registry is empty; got {row.get('TECHNOLOGY')!r}")
        for problem in _PO.validate_product_axes(
            family=row.get("PRODUCT_FAMILY"),
            product_type=row.get("PRODUCT_TYPE"),
            application=row.get("APPLICATION"),
            material=row.get("MATERIAL"),
            variant=row.get("VARIANT"),
        ):
            problems.append(f"{tag}: {problem}")
        key = candidate_identity(row)
        if key in identities:
            problems.append(f"{tag}: duplicate candidate identity {key}")
        identities.add(key)
    return tuple(problems)


def materializer_stats() -> dict[str, Any]:
    return {
        "authority": MATERIALIZER_AUTHORITY,
        "candidate_model_version": CANDIDATE_MODEL_VERSION,
        "candidate_source": CANDIDATE_SOURCE,
        "candidate_status": CANDIDATE_STATUS,
        "allowed_object_sources": list(ALLOWED_OBJECT_SOURCES),
        "mode_only_sources": list(MODE_ONLY_SOURCES),
        "forbidden_object_sources": list(FORBIDDEN_OBJECT_SOURCE_PREFIXES),
        "mode_source": MODE_SOURCE_SCOPE_AUTHORITY,
        "mode_source_acquisition": MODE_SOURCE_ACQUISITION,
        "mode_source_subject_acquisition": MODE_SOURCE_SUBJECT_ACQUISITION,
        "dwelling_goods_okpd_prefixes": list(DWELLING_GOODS_OKPD_PREFIXES),
        "dwelling_goods_okpd_coarse": list(DWELLING_GOODS_OKPD_COARSE),
        "acquisition_are_direct": ACQUISITION_ARE_DIRECT,
        "dwelling_acquisition_window": DWELLING_ACQUISITION_WINDOW,
        "scope_type_to_mode": dict(SCOPE_TYPE_TO_MODE),
        "skip_reasons": list(SKIP_REASONS),
        "materializable_applicability": list(MATERIALIZABLE_APPLICABILITY),
    }