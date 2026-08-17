"""DIRECT_SUPPLY requires independent direct-product evidence.

CONTEXTUAL_RESEARCH_PRIOR is search-context only. It must never, by itself,
create or preserve track=DIRECT_SUPPLY.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.domain.commercial_routing_v3 import OpportunityTrack, ProcurementForm, ResearchAction
from src.services.commercial_routing_v3.prior_semantics import PRIOR_KIND_COMMERCIAL_PRODUCT

DIRECT_SUPPLY_REQUIRES_DIRECT_PRODUCT_EVIDENCE = "DIRECT_SUPPLY_REQUIRES_DIRECT_PRODUCT_EVIDENCE"

_TITLE_IDENTITY: Dict[str, re.Pattern[str]] = {
    "lighting": re.compile(r"свет|освещ|прожектор|ламп|светильн", re.I),
    "computers": re.compile(r"ноутбук|компьютер|моноблок|сервер|\bпк\b", re.I),
    "waterproofing": re.compile(r"гидроизол|кровл|мембран|рулонн", re.I),
    "drainage_water_management": re.compile(r"дренаж|ливнев|водоотвед|ливневк", re.I),
    "curbstone": re.compile(r"бордюр|бортовой\s+камень|поребрик", re.I),
    "composite_structures": re.compile(r"композит|стеклопласт|композитн", re.I),
    "cable_support_systems": re.compile(
        r"кабельнесут|лотк\w+\s+кабел|кабельн\w+\s+(лотк|эстакад|консол|трей)",
        re.I,
    ),
    "composite_cable_trays": re.compile(r"композитн\w+\s+(лотк|трей)|лотк\w+\s+композит", re.I),
}


def _model_input(procurement: Dict[str, Any]) -> Dict[str, Any]:
    mi = procurement.get("v3_model_input")
    return mi if isinstance(mi, dict) else {}


def _text_blob(procurement: Dict[str, Any]) -> str:
    mi = _model_input(procurement)
    parts = [
        procurement.get("title"),
        procurement.get("auction_name"),
        mi.get("title"),
        mi.get("goods_description"),
        procurement.get("goods_description"),
        mi.get("okpd_name"),
        procurement.get("okpd_name"),
    ]
    return " ".join(str(p or "") for p in parts)


def _prior_category(row: Dict[str, Any]) -> str:
    return str(row.get("commercial_category_code") or row.get("category") or "").strip()


def collect_direct_product_evidence_sources(
    category: str,
    procurement: Dict[str, Any],
) -> List[str]:
    """Independent sources that may prove DIRECT_SUPPLY for this category.

    CONTEXTUAL_RESEARCH_PRIOR is never a source.
    """
    cat = str(category or "").strip()
    if not cat:
        return []
    mi = _model_input(procurement)
    sources: List[str] = []
    for row in mi.get("COMMERCIAL_PRODUCT_PRIORS") or []:
        if not isinstance(row, dict):
            continue
        if _prior_category(row) != cat:
            continue
        kind = str(row.get("prior_kind") or row.get("evidence_role") or "").upper()
        if kind == "CONTEXTUAL_RESEARCH_PRIOR":
            continue
        sources.append("COMMERCIAL_PRODUCT_PRIOR")
        break
    for row in mi.get("product_branch_trace") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("commercial_category_code") or "") != cat:
            continue
        if str(row.get("evidence_role") or "").upper() == PRIOR_KIND_COMMERCIAL_PRODUCT:
            sources.append("OKPD_PRODUCT_BRANCH_PRIOR")
            break
    blob = _text_blob(procurement)
    rx = _TITLE_IDENTITY.get(cat)
    if rx and rx.search(blob):
        if "TITLE_PRODUCT_IDENTITY" not in sources:
            sources.append("TITLE_PRODUCT_IDENTITY")
    return sources


def _apply_empty(
    out: Dict[str, Any],
    *,
    status: str,
    extra_reasons: List[str],
) -> None:
    reasons = [str(c) for c in (out.get("empty_hypothesis_reason_codes") or [])]
    for r in extra_reasons:
        if r not in reasons:
            reasons.append(r)
    out["commercial_category_hypotheses"] = []
    out["empty_hypothesis_status"] = status
    out["empty_hypothesis_reason_codes"] = reasons[:8]
    if status == "NO_COMMERCIAL_ENTRY":
        out["overall_research_action"] = ResearchAction.SKIP.value
        out["discovery_required"] = False
        out["review_required"] = False
    else:
        out["overall_research_action"] = ResearchAction.DISCOVER_COMMERCIAL_CATEGORY.value
        out["discovery_required"] = True
        out["review_required"] = True


def enforce_direct_supply_product_evidence(
    normalized: Dict[str, Any],
    procurement: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fail-closed: drop DIRECT_SUPPLY lacking independent product evidence."""
    out = dict(normalized or {})
    proc = procurement or {}
    mi = _model_input(proc)
    kept: List[Dict[str, Any]] = []
    rejected: List[str] = list(out.get("empty_hypothesis_reason_codes") or [])
    for h in list(out.get("commercial_category_hypotheses") or []):
        if not isinstance(h, dict):
            continue
        row = dict(h)
        track = str(row.get("opportunity_track") or "").upper()
        role = str(row.get("evidence_role") or "").upper()
        cat = str(row.get("category_code") or row.get("commercial_category_code") or "").strip()
        if track != OpportunityTrack.DIRECT_SUPPLY.value:
            kept.append(row)
            continue
        sources = collect_direct_product_evidence_sources(cat, proc)
        row["direct_product_evidence_sources"] = sources
        if role == "CONTEXTUAL_RESEARCH_PRIOR" and not sources:
            rejected.append(DIRECT_SUPPLY_REQUIRES_DIRECT_PRODUCT_EVIDENCE)
            continue
        if not sources:
            rejected.append(DIRECT_SUPPLY_REQUIRES_DIRECT_PRODUCT_EVIDENCE)
            continue
        if role == "CONTEXTUAL_RESEARCH_PRIOR":
            row["model_evidence_role"] = role
            if any(
                s in sources
                for s in ("COMMERCIAL_PRODUCT_PRIOR", "OKPD_PRODUCT_BRANCH_PRIOR")
            ):
                row["evidence_role"] = "COMMERCIAL_PRODUCT_PRIOR"
            else:
                row["evidence_role"] = "DIRECT_CATEGORY_EVIDENCE"
            rc = list(row.get("reason_codes") or [])
            if "direct_product_evidence_from_independent_source" not in rc:
                rc.append("direct_product_evidence_from_independent_source")
            row["reason_codes"] = rc[:6]
        kept.append(row)

    out["commercial_category_hypotheses"] = kept
    form = str(out.get("procurement_form") or "").upper()
    if kept:
        if rejected:
            reasons = [str(c) for c in (out.get("empty_hypothesis_reason_codes") or [])]
            for r in rejected:
                if r not in reasons:
                    reasons.append(r)
            out["empty_hypothesis_reason_codes"] = reasons[:8]
        return out

    dropped_direct = DIRECT_SUPPLY_REQUIRES_DIRECT_PRODUCT_EVIDENCE in rejected
    if form == ProcurementForm.DIRECT_GOODS_PURCHASE.value and dropped_direct:
        commercial = [
            p
            for p in (mi.get("COMMERCIAL_PRODUCT_PRIORS") or [])
            if isinstance(p, dict) and _prior_category(p)
        ]
        if commercial:
            _apply_empty(
                out,
                status="REVIEW_REQUIRED",
                extra_reasons=rejected + ["MODEL_DID_NOT_USE_AVAILABLE_PRIORS"],
            )
        else:
            _apply_empty(
                out,
                status="NO_COMMERCIAL_ENTRY",
                extra_reasons=rejected + [DIRECT_SUPPLY_REQUIRES_DIRECT_PRODUCT_EVIDENCE],
            )
        return out

    if rejected:
        reasons = [str(c) for c in (out.get("empty_hypothesis_reason_codes") or [])]
        for r in rejected:
            if r not in reasons:
                reasons.append(r)
        out["empty_hypothesis_reason_codes"] = reasons[:8]
    return out
