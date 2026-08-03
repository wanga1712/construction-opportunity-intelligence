"""
Краткое название компании для UI/PDF (без изменения full_name в БД).
Логика локальная для Streamlit — не зависит от property display_name в pythonProject89.
"""
import re
from typing import Any, Optional

_QUOTE_CHARS = "\"'«»""''"

_LEGAL_PREFIX_PATTERNS = (
    r"общество\s+с\s+ограниченной\s+ответственностью",
    r"публичное\s+акционерное\s+общество",
    r"открытое\s+акционерное\s+общество",
    r"закрытое\s+акционерное\s+общество",
    r"акционерное\s+общество",
    r"научно[\-\s]*производственное\s+объединение",
    r"индивидуальный\s+предприниматель",
    r"государственное\s+унитарное\s+предприятие",
    r"муниципальное\s+унитарное\s+предприятие",
    r"федеральное\s+государственное\s+унитарное\s+предприятие",
    r"проектно[\-\s]*изыскательское\s+объединение",
    r"проектно[\-\s]*конструкторское\s+бюро",
    r"проектное\s+бюро",
    r"группа\s+компаний",
    r"проектировщик\s*:?",
    r"подрядчик\s*:?",
    r"генеральный\s+подрядчик\s*:?",
    r"\bооо\b",
    r"\bао\b",
    r"\bпао\b",
    r"\bзао\b",
    r"\bоао\b",
    r"\bип\b",
    r"\bнпо\b",
    r"\bгуп\b",
    r"\bмуп\b",
    r"\bфгуп\b",
    r"\bгк\b",
    r"\bпки\b",
    r"\bпкб\b",
)

_SEP_RE = re.compile(r"^[\s\"'«»\-–—,.:;]+")


def _strip_outer_quotes(text: str) -> str:
    value = text.strip()
    while len(value) >= 2 and value[0] in _QUOTE_CHARS and value[-1] in _QUOTE_CHARS:
        value = value[1:-1].strip()
    return value


def _strip_known_prefixes(name: str) -> str:
    value = name
    changed = True
    while changed:
        changed = False
        for pattern in _LEGAL_PREFIX_PATTERNS:
            regex = re.compile(
                rf"^{pattern}(?:[\s\"'«»\-–—,.:;]+|$)",
                re.IGNORECASE | re.UNICODE,
            )
            match = regex.match(value)
            if match:
                value = value[match.end() :]
                value = _SEP_RE.sub("", value)
                changed = True
                break
    return value


def format_company_display_name(
    full_name: Optional[str],
    legal_form: Optional[str] = None,
) -> str:
    if not full_name:
        return "—"

    original = " ".join(str(full_name).split())
    name = original

    if legal_form:
        lf = " ".join(str(legal_form).split())
        if lf and name.lower().startswith(lf.lower()):
            name = name[len(lf) :]
            name = _SEP_RE.sub("", name)

    name = _strip_known_prefixes(name)
    name = _strip_outer_quotes(name)
    name = _strip_known_prefixes(name)
    name = _strip_outer_quotes(name)
    name = name.strip(_QUOTE_CHARS + " ")
    name = " ".join(name.split())

    return name or original


def get_company_display_name(company: Any) -> str:
    """Безопасно для любого объекта компании с полями full_name / legal_form."""
    full_name = getattr(company, "full_name", None)
    legal_form = getattr(company, "legal_form", None)
    return format_company_display_name(full_name, legal_form)
