"""Procurement form classification — not OKPD-only."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from src.domain.commercial_routing_v3 import ProcurementForm

_DIRECT_SUPPLY_RE = re.compile(
    r"\b(поставк[аиуе]|закупк[аиуе]\s+товар|приобретени[ея]\s+товар|"
    r"светильник|компьютер|сервер|ноутбук|принтер|ламп[аы])\b",
    re.IGNORECASE,
)
_CONSTRUCTION_RE = re.compile(
    r"\b(строительств[оа]|реконструкц|капитальн\w+\s+ремонт|"
    r"благоустройств|устройств\w+\s+(дорог|сет|полотн)|монтаж\s+конструкц)\b",
    re.IGNORECASE,
)
_DESIGN_ONLY_RE = re.compile(
    r"\b(проектн\w+\s+документац|разработк\w+\s+проект|проектирован|"
    r"изыскани[яе]|архитектурн\w+\s+концепц)\b",
    re.IGNORECASE,
)
_SURVEY_DESIGN_RE = re.compile(
    r"\b(инженерн\w+\s+изыскани|изыскани\w+\s+и\s+проект)\b",
    re.IGNORECASE,
)
_DESIGN_BUILD_RE = re.compile(
    r"\b(проектировани\w+\s+и\s+строительств|проектно-изыскательск\w+\s+работ\w+\s+и\s+строительств)\b",
    re.IGNORECASE,
)
_DESIGN_EXPERTISE_BUILD_RE = re.compile(
    r"\b(экспертиз\w+\s+проект|проектн\w+.*экспертиз)\b",
    re.IGNORECASE,
)


def classify_procurement_form(procurement: Dict[str, Any]) -> ProcurementForm:
    """Classify procurement form using title, OKPD, and metadata — not OKPD alone."""
    title = (procurement.get("title") or procurement.get("auction_name") or "").lower()
    okpd_name = (procurement.get("okpd_name") or "").lower()
    combined = f"{title} {okpd_name}"

    if _DIRECT_SUPPLY_RE.search(title):
        return ProcurementForm.DIRECT_GOODS_PURCHASE

    if _DESIGN_EXPERTISE_BUILD_RE.search(combined):
        return ProcurementForm.DESIGN_EXPERTISE_AND_BUILD
    if _DESIGN_BUILD_RE.search(combined):
        return ProcurementForm.DESIGN_AND_BUILD
    if _SURVEY_DESIGN_RE.search(combined):
        return ProcurementForm.SURVEY_AND_DESIGN
    if _DESIGN_ONLY_RE.search(combined):
        return ProcurementForm.DESIGN_ONLY

    if _CONSTRUCTION_RE.search(combined):
        return ProcurementForm.CONSTRUCTION_WORKS

    # Broad construction OKPD but direct supply title already handled above
    okpd = (procurement.get("okpd_code") or "").strip()
    if okpd.startswith(("41.", "42.", "43.")):
        if any(w in title for w in ("поставк", "закупк", "приобретени")):
            return ProcurementForm.DIRECT_GOODS_PURCHASE
        return ProcurementForm.CONSTRUCTION_WORKS

    if okpd.startswith("26."):
        return ProcurementForm.DIRECT_GOODS_PURCHASE

    if okpd.startswith(("71.", "74.")):
        return ProcurementForm.DESIGN_ONLY

    return ProcurementForm.UNKNOWN


def procurement_form_priors(procurement: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return heuristic priors for AI context."""
    form = classify_procurement_form(procurement)
    return [{"procurement_form": form.value, "source": "deterministic_heuristic"}]


_PRODUCT_OKPD_PREFIXES = ("26.", "27.", "28.", "32.")
_WORKS_OKPD_PREFIXES = ("41.", "42.", "43.")
_PRODUCT_NOUN_RE = re.compile(
    r"("
    r"трансформатор|компьютер|ноутбук|светильник|сервер|принтер|"
    r"счетчик|кабел|сетев\w+\s+оборуд|выключатель|ламп"
    r")",
    re.I,
)
_STRONG_OBJECT_RE = re.compile(
    r"("
    r"капитальн\w*\s+ремонт|капремонт|"
    r"строительств\w*\s+(дорог|мост|водопровод|здани|школ|объект)|"
    r"реконструкц\w*\s+(дорог|мост|здани|школ|объект)|"
    r"ремонт\w*\s+(дорог|мост|путепровод|покрыти)|"
    r"проектирован\w+\s+объект|изыскан\w+.+\s+проект"
    r")",
    re.I,
)
_CAPITAL_SCHOOL_RE = re.compile(
    r"капитальн\w*\s+ремонт|капремонт|реконструкц",
    re.I,
)
_SCHOOL_RE = re.compile(r"школ|образовательн", re.I)
_ROAD_BRIDGE_RE = re.compile(r"дорог|мост|путепровод|водопровод", re.I)


def _form_title_and_codes(procurement: Dict[str, Any]) -> Tuple[str, List[str]]:
    mi = procurement.get("v3_model_input") if isinstance(procurement.get("v3_model_input"), dict) else {}
    title = str(
        procurement.get("title")
        or procurement.get("auction_name")
        or mi.get("title")
        or ""
    )
    codes = [str(c) for c in (mi.get("okpd_codes") or []) if c]
    if procurement.get("okpd_code"):
        code = str(procurement["okpd_code"])
        if code not in codes:
            codes.insert(0, code)
    return title, codes


def strong_direct_goods_evidence(procurement: Dict[str, Any]) -> Tuple[bool, str]:
    """True when title/OKPD prove a goods purchase, not an object/work job."""
    title, codes = _form_title_and_codes(procurement)
    mi = procurement.get("v3_model_input") if isinstance(procurement.get("v3_model_input"), dict) else {}
    low = title.lower()
    supply_word = bool(_DIRECT_SUPPLY_RE.search(title) or "поставк" in low)
    product_okpd = any(c.startswith(_PRODUCT_OKPD_PREFIXES) for c in codes)
    product_noun = bool(_PRODUCT_NOUN_RE.search(title))
    commercial_prior = bool(mi.get("COMMERCIAL_PRODUCT_PRIORS"))
    if supply_word and product_okpd:
        return True, "TITLE_POSTAVKA+PRODUCT_OKPD"
    if supply_word and product_noun:
        return True, "TITLE_POSTAVKA+PRODUCT_NOUN"
    if supply_word and commercial_prior:
        return True, "TITLE_POSTAVKA+COMMERCIAL_PRODUCT_PRIOR"
    if product_okpd and product_noun:
        return True, "PRODUCT_OKPD+PRODUCT_NOUN"
    return False, "NO_STRONG_DIRECT_GOODS"


def strong_object_procurement_evidence(procurement: Dict[str, Any]) -> Tuple[bool, str]:
    """True for explicit construction/design/work objects. OKPD prefix alone is not enough."""
    title, codes = _form_title_and_codes(procurement)
    works_okpd = any(c.startswith(_WORKS_OKPD_PREFIXES) for c in codes)
    if _CAPITAL_SCHOOL_RE.search(title) and _SCHOOL_RE.search(title):
        return True, "CAPITAL_REPAIR_SCHOOL"
    if _STRONG_OBJECT_RE.search(title):
        if works_okpd or _ROAD_BRIDGE_RE.search(title) or _SCHOOL_RE.search(title):
            return True, "OBJECT_WORK_SEMANTICS"
    if works_okpd and _CONSTRUCTION_RE.search(title):
        return True, "CONSTRUCTION_TITLE+WORKS_OKPD"
    return False, "NO_STRONG_OBJECT"
