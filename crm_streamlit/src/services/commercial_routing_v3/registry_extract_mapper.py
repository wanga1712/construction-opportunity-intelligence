"""Deterministic registry mapper from model extraction (Architecture B).

Provenance: BUSINESS_RULE_FROM_MODEL_EXTRACTION — never impersonates MODEL_VALIDATED.
Vocabulary comes only from live registry fields (names, aliases, signals, terms).
No arbitrary hardcoded product→category switches.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

PROVENANCE = "BUSINESS_RULE_FROM_MODEL_EXTRACTION"


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().replace("ё", "е").split())


def _as_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        out = []
        for x in raw:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                for k in ("term", "alias", "signal", "name", "value"):
                    if x.get(k):
                        out.append(str(x[k]))
                        break
        return out
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return _as_list(parsed)
        except Exception:
            return [raw] if raw.strip() else []
    return []


@dataclass
class RegistryVocab:
    term_to_codes: Dict[str, Set[str]] = field(default_factory=dict)
    terms_sorted: List[str] = field(default_factory=list)
    gaps_checked: List[str] = field(default_factory=list)


def build_registry_vocabulary(crm_db, registry: List[Dict[str, Any]]) -> RegistryVocab:
    """Index searchable phrases from registry metadata only."""
    vocab = RegistryVocab()
    allowed = {str(c.get("category_code")) for c in registry if c.get("category_code")}

    def add(term: str, code: str) -> None:
        t = _norm(term)
        if len(t) < 3 or code not in allowed:
            return
        vocab.term_to_codes.setdefault(t, set()).add(code)

    for c in registry:
        code = str(c.get("category_code") or "")
        add(code, code)
        add(str(c.get("category_name") or ""), code)
        add(str(c.get("description") or ""), code)

    # Optional columns on crm_product_categories
    try:
        rows = crm_db.execute_query(
            """
            SELECT category_code, category_name, aliases, positive_signals
            FROM crm_product_categories
            WHERE is_active = TRUE
            """
        ) or []
        for r in rows:
            code = str(r.get("category_code") or "")
            if code not in allowed:
                continue
            add(str(r.get("category_name") or ""), code)
            for a in _as_list(r.get("aliases")):
                add(a, code)
            for s in _as_list(r.get("positive_signals")):
                add(s, code)
    except Exception:
        pass

    # Subcategory names/codes
    try:
        rows = crm_db.execute_query(
            """
            SELECT c.category_code, s.subcategory_code, s.subcategory_name
            FROM crm_product_subcategories s
            JOIN crm_product_categories c ON c.id = s.category_id
            WHERE c.is_active = TRUE AND s.is_active = TRUE
            """
        ) or []
        for r in rows:
            code = str(r.get("category_code") or "")
            add(str(r.get("subcategory_code") or ""), code)
            add(str(r.get("subcategory_name") or ""), code)
    except Exception:
        pass

    # Search terms table if present
    try:
        rows = crm_db.execute_query(
            """
            SELECT c.category_code, t.term
            FROM crm_product_subcategory_terms t
            JOIN crm_product_subcategories s ON s.id = t.subcategory_id
            JOIN crm_product_categories c ON c.id = s.category_id
            WHERE c.is_active = TRUE AND s.is_active = TRUE
              AND COALESCE(t.term_type, 'search') IN ('search', 'alias', 'brand')
            """
        ) or []
        for r in rows:
            add(str(r.get("term") or ""), str(r.get("category_code") or ""))
    except Exception:
        pass

    vocab.terms_sorted = sorted(vocab.term_to_codes.keys(), key=lambda t: (-len(t), t))
    return vocab


def map_extracted_to_categories(
    extraction: Dict[str, Any],
    vocab: RegistryVocab,
    *,
    allowed: Set[str],
) -> Dict[str, Any]:
    """Map extracted procured_items to ACTIVE codes via registry vocabulary only."""
    form = str(extraction.get("procurement_form") or "UNKNOWN")
    items = [str(x) for x in (extraction.get("procured_items") or []) if x]
    evidence = [str(x) for x in (extraction.get("explicit_product_evidence") or []) if x]
    families = [str(x) for x in (extraction.get("material_families") or []) if x]
    is_service = bool(extraction.get("is_service"))

    gaps: List[str] = []
    mapped: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    if is_service or form == "SERVICES_OTHER":
        return {
            "provenance": PROVENANCE,
            "commercial_category_hypotheses": [],
            "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
            "overall_research_action": "SKIP",
            "mapped_from": [],
            "registry_vocabulary_gaps": [],
            "EXTRACT_MAP_IMPERSONATES_MODEL": False,
        }

    blobs = items + evidence + families
    for phrase in blobs:
        p = _norm(phrase)
        if not p:
            continue
        hit_code = None
        hit_term = None
        for term in vocab.terms_sorted:
            if term in p or p in term:
                codes = [c for c in vocab.term_to_codes[term] if c in allowed]
                if len(codes) == 1:
                    hit_code = codes[0]
                    hit_term = term
                    break
                if len(codes) > 1:
                    # ambiguous vocabulary — do not invent
                    gaps.append(f"ambiguous:{phrase}->{sorted(codes)}")
                    hit_code = None
                    break
        if hit_code and hit_code not in seen:
            seen.add(hit_code)
            mapped.append(
                {
                    "category_code": hit_code,
                    "opportunity_track": "DIRECT_SUPPLY"
                    if form == "DIRECT_GOODS_PURCHASE"
                    else "EMBEDDED_MATERIAL",
                    "confidence": None,  # never fabricate model confidence
                    "confirmation_required": form != "DIRECT_GOODS_PURCHASE",
                    "evidence_role": "DIRECT_CATEGORY_EVIDENCE"
                    if form == "DIRECT_GOODS_PURCHASE"
                    else "CONTEXTUAL_RESEARCH_PRIOR",
                    "reason_codes": [f"registry_vocab_match:{hit_term}"],
                    "research_action": "LIGHT_RESEARCH",
                    "subcategory_code": "SUBCATEGORY_NOT_ASSIGNED",
                    "mapping_source_term": hit_term,
                    "mapping_source_phrase": phrase,
                }
            )
        elif hit_code is None and phrase.strip():
            # check if phrase looks like a product word with no vocab
            if form == "DIRECT_GOODS_PURCHASE" and len(p) >= 4:
                gaps.append(phrase)

    # Object forms without mapped material: empty review
    if form.startswith("DESIGN") or form in ("CONSTRUCTION_WORKS", "WORKS_OTHER"):
        if not mapped:
            return {
                "provenance": PROVENANCE,
                "commercial_category_hypotheses": [],
                "empty_hypothesis_status": "INSUFFICIENT_EVIDENCE",
                "overall_research_action": "LIGHT_RESEARCH",
                "mapped_from": blobs,
                "registry_vocabulary_gaps": gaps,
                "EXTRACT_MAP_IMPERSONATES_MODEL": False,
            }

    if form == "DIRECT_GOODS_PURCHASE" and not mapped:
        return {
            "provenance": PROVENANCE,
            "commercial_category_hypotheses": [],
            "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY"
            if not gaps
            else "REVIEW_REQUIRED",
            "overall_research_action": "SKIP" if not gaps else "LIGHT_RESEARCH",
            "mapped_from": blobs,
            "registry_vocabulary_gaps": gaps,
            "EXTRACT_MAP_IMPERSONATES_MODEL": False,
        }

    return {
        "provenance": PROVENANCE,
        "commercial_category_hypotheses": mapped[:3],
        "empty_hypothesis_status": None if mapped else "NO_COMMERCIAL_ENTRY",
        "overall_research_action": "LIGHT_RESEARCH" if mapped else "SKIP",
        "mapped_from": blobs,
        "registry_vocabulary_gaps": gaps,
        "EXTRACT_MAP_IMPERSONATES_MODEL": False,
    }


def check_vocabulary_gaps_for_phrases(
    phrases: List[str], vocab: RegistryVocab, allowed: Set[str]
) -> List[str]:
    """Return phrases that do not uniquely map via registry vocabulary."""
    gaps = []
    for phrase in phrases:
        p = _norm(phrase)
        found = False
        for term in vocab.terms_sorted:
            if term in p or p in term:
                codes = [c for c in vocab.term_to_codes[term] if c in allowed]
                if len(codes) == 1:
                    found = True
                    break
        if not found:
            gaps.append(phrase)
    return gaps
