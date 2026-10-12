"""Deterministic pre-research procurement-scope gate (no model).

WIP=MASS-CANONICAL-OBJECT-LAYER-RUN-V1, Stage A ("deterministic mode gate").

The production scope authority (``crm_procurement_scope_authority``) is the
primary, stored source of ``procurement_scope_type``.  It only covers the
procurements that were already admitted to pre-research; the vast majority of
the base has no row at all.

For those rows this module re-runs the *same* fail-closed pre-research rule set
that produced the stored authority rows (``pre_research_rules_v1`` /
``scope_version=1.1``) so the mass run can resolve a procurement mode
deterministically before ever asking a model.  Only a title / OKPD are needed.

This is a faithful port of the deployed v1.1 classifier; the regexes are kept
verbatim so the derivation stays consistent with the stored authority.  It
never writes anything and never invents a mode: an unresolved row returns
``UNKNOWN``, which the caller must escalate (to Qwen), never guess.
"""
from __future__ import annotations

import re
from typing import Any

from src.services import product_candidate_materializer as _MAT
from src.services import product_ontology as _PO

PRE_RESEARCH_MODEL = "pre_research_rules_v1"
PRE_RESEARCH_VERSION = "1.1"
MODE_SOURCE_PRE_RESEARCH = "PRE_RESEARCH_SCOPE_GATE"

SCOPE_DIRECT_GOODS = "DIRECT_GOODS"
SCOPE_WORKS_EMBEDDED = "WORKS_WITH_EMBEDDED_PRODUCTS"
SCOPE_DESIGN = "DESIGN_PROJECT"
SCOPE_EQUIPMENT_INSTALL = "EQUIPMENT_AND_INSTALLATION"
SCOPE_SERVICE_CONSUMABLES = "SERVICE_WITH_CONSUMABLES"
SCOPE_PURE_SERVICE = "PURE_SERVICE"
SCOPE_MIXED = "MIXED"
SCOPE_UNKNOWN = "UNKNOWN"

# Scope vocabulary of this gate -> canonical PROCUREMENT_MODE.  UNKNOWN is
# deliberately absent: it is "not yet resolved", never a mode.
PRE_RESEARCH_SCOPE_TO_MODE = {
    SCOPE_DIRECT_GOODS: _PO.PROCUREMENT_MODE_DIRECT,
    SCOPE_WORKS_EMBEDDED: _PO.PROCUREMENT_MODE_OBJECT,
    SCOPE_PURE_SERVICE: _PO.PROCUREMENT_MODE_SERVICE_NO_OBJECT,
    SCOPE_SERVICE_CONSUMABLES: _PO.PROCUREMENT_MODE_SERVICE_NO_OBJECT,
    SCOPE_DESIGN: _PO.PROCUREMENT_MODE_AMBIGUOUS,
    SCOPE_EQUIPMENT_INSTALL: _PO.PROCUREMENT_MODE_AMBIGUOUS,
    SCOPE_MIXED: _PO.PROCUREMENT_MODE_AMBIGUOUS,
}

_SUPPLY_RE = re.compile(r"поставк|приобретени|закупк\w*\s+товар", re.I)
_WORK_RE = re.compile(
    r"строительств|реконструкц|капитальн\w*\s+ремонт|текущ\w*\s+ремонт|"
    r"устройств\w+\s+(дорог|сет|полотн)|выполнени\w*\s+работ", re.I
)
_DESIGN_RE = re.compile(
    r"проектн\w*\s+документац|разработк\w*\s+проект|проектирован|"
    r"инженерн\w*\s+изыскани|рабоч\w*\s+документац", re.I
)
_SERVICE_RE = re.compile(
    r"оказани\w*\s+услуг|техническ\w*\s+обслужив|обслужив|уборк|диагностик", re.I
)
_INSTALL_RE = re.compile(r"монтаж|пусконалад|установк", re.I)
_CONSUMABLE_RE = re.compile(r"материал|расходн|комплектующ", re.I)
_PRODUCT_RE = re.compile(
    r"линолеум|ламп|светильник|компьютер|сервер|принтер|кабел|"
    r"оборудован|покрыти\w*\s+пола|плитк|материал", re.I
)
_PRODUCT_OKPD_PREFIXES = (
    "20.", "21.", "22.", "23.", "24.", "25.", "26.", "27.",
    "28.", "29.", "30.", "31.", "32.",
)


def classify_pre_research_scope(title: Any, okpd_code: Any = None) -> dict[str, Any]:
    """Fail-closed pre-research scope classification from title + OKPD only."""
    text = str(title or "")
    lower = text.lower()
    okpd = [str(okpd_code).strip()] if okpd_code else []
    has_supply = bool(_SUPPLY_RE.search(text))
    has_work = bool(_WORK_RE.search(text))
    has_design = bool(_DESIGN_RE.search(text))
    has_service = bool(_SERVICE_RE.search(text))
    has_install = bool(_INSTALL_RE.search(text))
    has_consumable = bool(_CONSUMABLE_RE.search(text))
    has_product = bool(_PRODUCT_RE.search(text))
    product_okpd = any(code.startswith(_PRODUCT_OKPD_PREFIXES) for code in okpd)

    if has_design and has_work and has_supply:
        scope, reason = SCOPE_MIXED, "design+works+supply"
    elif has_supply and has_install and ("оборудован" in lower or product_okpd):
        scope, reason = SCOPE_EQUIPMENT_INSTALL, "supply+installation"
    elif has_design:
        scope, reason = SCOPE_DESIGN, "explicit_design"
    elif has_work:
        scope, reason = SCOPE_WORKS_EMBEDDED, "explicit_works"
    elif has_service and has_consumable:
        scope, reason = SCOPE_SERVICE_CONSUMABLES, "service+consumables"
    elif has_service and not has_supply:
        scope, reason = SCOPE_PURE_SERVICE, "explicit_service"
    elif has_supply and (has_product or product_okpd):
        scope, reason = SCOPE_DIRECT_GOODS, "explicit_supply+product_evidence"
    elif has_product and product_okpd and not (has_work or has_design or has_service):
        scope, reason = SCOPE_DIRECT_GOODS, "product_subject+product_okpd"
    else:
        scope, reason = SCOPE_UNKNOWN, "insufficient_pre_research_evidence"
    return {"procurement_scope_type": scope, "scope_method": reason}


def pre_research_mode(title: Any, okpd_code: Any = None) -> str | None:
    """Canonical mode from the pre-research gate, or None when UNKNOWN."""
    scope = classify_pre_research_scope(title, okpd_code)
    return PRE_RESEARCH_SCOPE_TO_MODE.get(scope["procurement_scope_type"])


def pre_research_scope_to_mode(scope_type: Any) -> str | None:
    """Map an already-derived pre-research scope vocabulary to a mode."""
    return PRE_RESEARCH_SCOPE_TO_MODE.get(str(scope_type or "").strip().upper())


def resolve_mode_with_fallback(
    stored_scope_type: Any,
    *,
    has_stored_row: bool,
    title: Any = None,
    okpd_code: Any = None,
) -> tuple[str | None, str]:
    """(mode, mode_source) using the stored authority first, gate as fallback.

    Dwelling-acquisition rules always win (they are the approved DIRECT
    remediation and must not regress on a full re-run).
    """
    mode, source = _MAT.resolve_procurement_mode_with_source(
        stored_scope_type if has_stored_row else None, title=title, okpd_code=okpd_code
    )
    if source in (_MAT.MODE_SOURCE_ACQUISITION, _MAT.MODE_SOURCE_SUBJECT_ACQUISITION):
        return mode, source
    if has_stored_row:
        return mode, source
    derived = pre_research_mode(title, okpd_code)
    if derived is None:
        return None, MODE_SOURCE_PRE_RESEARCH
    return derived, MODE_SOURCE_PRE_RESEARCH


def scope_gate_stats() -> dict[str, Any]:
    return {
        "model": PRE_RESEARCH_MODEL,
        "version": PRE_RESEARCH_VERSION,
        "mode_source": MODE_SOURCE_PRE_RESEARCH,
        "scope_to_mode": dict(PRE_RESEARCH_SCOPE_TO_MODE),
    }