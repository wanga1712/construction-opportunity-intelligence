"""Object-routing label contract for TRAINING STAGE 1 (object type, not medals).

The model learns exactly three independent binary signals:

    SOCIAL          object or buyer is a social-purpose facility
    PROJECT         the contract contains construction / repair / design works
    DIRECT_SUPPLY   the subject of the contract is supply of goods

It deliberately does NOT learn GOLD/SILVER/BRONZE/WOOD, commercial category or
priority_score.  Ground truth comes from the project's existing deterministic
routing authority (see ``PROJECT_SCOPE_TYPES``/``SUPPLY_SCOPE_TYPES`` below),
never from old model medals.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.learning.procurement_scope.classifier import ProcurementScopeClassifierV1
from src.services.expert_object_taxonomy import OBJECT_TYPES_BY_SECTOR, SOCIAL

PROMPT_VERSION = "object_routing_prompt_v2"
LABELS = ("SOCIAL", "PROJECT", "DIRECT_SUPPLY")

#: Canonical social object types from the project object taxonomy.
SOCIAL_OBJECT_TYPES = frozenset(code for code, _ in OBJECT_TYPES_BY_SECTOR[SOCIAL])

#: Procurement scope types (existing classifier) that mean "there is a project".
PROJECT_SCOPE_TYPES = frozenset(
    {"WORKS_WITH_EMBEDDED_PRODUCTS", "DESIGN_PROJECT", "EQUIPMENT_AND_INSTALLATION"}
)

#: Procurement scope types that mean "goods are supplied".
SUPPLY_SCOPE_TYPES = frozenset(
    {"DIRECT_GOODS", "EQUIPMENT_AND_INSTALLATION", "SERVICE_WITH_CONSUMABLES"}
)

#: OKPD2 section fallbacks, used only when the title is inconclusive (UNKNOWN).
WORKS_SECTIONS = frozenset({"41", "42", "43"})
DESIGN_PREFIX = "71.12"
GOODS_SECTIONS = frozenset(
    {"10", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24",
     "25", "26", "27", "28", "29", "30", "31", "32", "33", "35", "38"}
)

#: Social-purpose markers in buyer name or purchase title.
SOCIAL_PATTERNS = (
    r"школ", r"лице[йя]", r"гимнази", r"детск\w*\s+сад", r"детсад", r"дошкольн",
    r"ясли", r"интернат", r"больниц", r"поликлиник", r"госпитал", r"диспансер",
    r"амбулатор", r"фельдшерск", r"роддом", r"перинатальн", r"санатор",
    r"стационар", r"центр гигиены", r"станц\w*\s+скорой", r"скорой помощи",
    r"дюсш", r"сдюшор", r"спортивн\w*\s+школ", r"спортшкол", r"физкультур",
    r"стадион", r"бассейн", r"дом культуры", r"дворец культуры",
    r"дворец творчества", r"дворец спорта", r"библиотек", r"музе[йя]", r"театр",
    r"цирк", r"филармони", r"школ\w*\s+искусств", r"музыкальн\w*\s+школ",
    r"художественн\w*\s+школ", r"центр детского творчества", r"детск\w*\s+дом",
    r"геронтолог", r"пансионат для", r"оздоровительн", r"лагер",
    r"университет", r"институт", r"академи", r"колледж", r"техникум", r"училищ",
    r"образовательн", r"туберкулезн", r"онкодиспансер", r"психоневролог",
    r"женск\w*\s+консультац", r"хоспис", r"мед\w*\s+центр", r"детск\w*\s+поликлиник",
)

_SOCIAL_REGEXES = tuple(re.compile(p) for p in SOCIAL_PATTERNS)
_CLASSIFIER = ProcurementScopeClassifierV1()

SYSTEM_PROMPT = (
    "Ты классификатор госзакупок. Определи три независимых признака и ответь только JSON."
)

USER_TEMPLATE = (
    "{title}\n"
    "ОКПД2: {okpd} {okpd_name}\n"
    "Заказчик: {customer}\n"
    "Объект: {object_type}\n"
    "SOCIAL: объект/заказчик социального назначения (школа, садик, больница, культура, спорт, вуз)\n"
    "PROJECT: в контракте есть СМР, ремонт, проектирование или монтаж\n"
    "DIRECT_SUPPLY: предмет контракта — поставка товара\n"
    'JSON: {{"SOCIAL":true|false,"PROJECT":true|false,"DIRECT_SUPPLY":true|false}}'
)


def normalize_okpd(code: Optional[str]) -> str:
    return re.sub(r"\s+", "", str(code or "")).strip()


def derive_labels(
    title: Optional[str],
    okpd_code: Optional[str] = "",
    okpd_name: Optional[str] = "",
    customer: Optional[str] = "",
    object_type: Optional[str] = "",
) -> Dict[str, bool]:
    """Deterministic teacher labels from the project's existing routing rules.

    Scope comes from ``ProcurementScopeClassifierV1``; SOCIAL comes from the
    canonical object taxonomy plus social-purpose markers in buyer/title.
    ``initial_price`` is intentionally not an input: price never creates meaning.
    """
    title_text = str(title or "").strip()
    okpd = normalize_okpd(okpd_code)
    scope = _CLASSIFIER.classify(title_text, [okpd] if okpd else []).get("procurement_scope_type")

    haystack = "%s %s" % (customer or "", title_text)
    lowered = haystack.lower()
    social = str(object_type or "").strip().upper() in SOCIAL_OBJECT_TYPES or any(
        rx.search(lowered) for rx in _SOCIAL_REGEXES
    )

    project = scope in PROJECT_SCOPE_TYPES
    supply = scope in SUPPLY_SCOPE_TYPES

    if scope == "UNKNOWN":
        section = okpd[:2]
        if section in WORKS_SECTIONS or okpd.startswith(DESIGN_PREFIX):
            project = True
        elif section in GOODS_SECTIONS:
            supply = True

    return {"SOCIAL": bool(social), "PROJECT": bool(project), "DIRECT_SUPPLY": bool(supply)}


def target_json(labels: Dict[str, Any]) -> str:
    """Canonical compact target string, stable key order."""
    parts = ", ".join(
        '"%s": %s' % (name, "true" if labels.get(name) else "false") for name in LABELS
    )
    return "{%s}" % parts


def build_user_message(record: Dict[str, Any], *, max_title: int = 120, max_okpd_name: int = 55) -> str:
    return USER_TEMPLATE.format(
        title=str(record.get("title") or "")[:max_title],
        okpd=normalize_okpd(record.get("okpd_code")) or "-",
        okpd_name=str(record.get("okpd_name") or "")[:max_okpd_name],
        customer=str(record.get("customer") or "-")[:70],
        object_type=str(record.get("object_type") or "-")[:40],
    )


def build_example(record: Dict[str, Any]) -> Dict[str, Any]:
    """One supervised example: chat messages + target + provenance."""
    labels = derive_labels(
        title=record.get("title"),
        okpd_code=record.get("okpd_code"),
        okpd_name=record.get("okpd_name"),
        customer=record.get("customer"),
        object_type=record.get("object_type"),
    )
    return {
        "crm_id": record.get("id"),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(record)},
            {"role": "assistant", "content": target_json(labels)},
        ],
        "labels": labels,
        "prompt_version": PROMPT_VERSION,
    }


def parse_labels(text: str) -> Optional[Dict[str, bool]]:
    """Parse a model answer into the three booleans (tolerant, deterministic)."""
    import json

    raw = str(text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(raw[start : end + 1])
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    out: Dict[str, bool] = {}
    for name in LABELS:
        value = payload.get(name)
        if isinstance(value, bool):
            out[name] = value
        elif isinstance(value, str) and value.strip().lower() in ("true", "false"):
            out[name] = value.strip().lower() == "true"
        else:
            return None
    return out