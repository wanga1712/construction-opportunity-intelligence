"""Title+OKPD heuristics for genuine construction/infrastructure objects.

OKPD prefix 41/42/43 alone is NOT sufficient (rentals, fences, services).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# Strong construction / infrastructure title signals (Russian).
_CONSTRUCTION_TITLE_POS = re.compile(
    r"("
    r"строительств|реконструкц|капремонт|капитальн\w*\s+ремонт|"
    r"дорожн|асфальт|мост|путепровод|газопровод|водопровод|"
    r"инженерн\w*\s+инфраструктур|здани[ея]|сооружен|"
    r"фундамент|кровел|фасад|дорог[аиуе]|"
    r"благоустройств|линейн\w*\s+объект"
    r")",
    re.I,
)

# Titles that look like rental/service despite works OKPD.
_CONSTRUCTION_TITLE_NEG = re.compile(
    r"("
    r"аренда|прокат|лизинг|монтаж[,\s]+демонтаж\s+имуществ|"
    r"временн\w*\s+огражден|охран\w*\s+услуг|клининг|"
    r"поставк\w+\s+счетчик|комплектующ"
    r")",
    re.I,
)

_WORKS_OKPD = ("41.", "42.", "43.")


def is_genuine_construction_object(
    *,
    title: str,
    okpd_codes: List[str] | None = None,
    okpd_code: str | None = None,
) -> Tuple[bool, str]:
    """Return (is_construction, reason). Requires title evidence; OKPD alone insufficient."""
    title_s = str(title or "").strip()
    codes = list(okpd_codes or [])
    if okpd_code and str(okpd_code) not in codes:
        codes.insert(0, str(okpd_code))
    works_okpd = any(
        c.startswith(_WORKS_OKPD) or any(c.startswith(p) for p in _WORKS_OKPD) for c in codes
    )
    if _CONSTRUCTION_TITLE_NEG.search(title_s):
        return False, "TITLE_NEGATIVE_RENTAL_OR_SERVICE"
    if not _CONSTRUCTION_TITLE_POS.search(title_s):
        return False, "TITLE_NO_CONSTRUCTION_SIGNAL"
    if works_okpd:
        return True, "TITLE_CONSTRUCTION_SIGNAL+WORKS_OKPD"
    return True, "TITLE_CONSTRUCTION_SIGNAL"


def card_is_genuine_construction(card_or_mi: Dict[str, Any]) -> Tuple[bool, str]:
    return is_genuine_construction_object(
        title=str(card_or_mi.get("title") or ""),
        okpd_codes=list(card_or_mi.get("okpd_codes") or []),
        okpd_code=card_or_mi.get("okpd_code"),
    )
