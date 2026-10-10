"""Project-documentation metadata reader (R4-PD): organizations and people.

Rule (docs/CRM_V3_LAUNCH_ROADMAP.md, R4-PD): only explicitly stated facts.
Every occurrence keeps a raw value and the exact source quote; role vocabulary
is OPEN (ГИП/ГАП/… are examples, unseen wording must still be captured).
These are NOT product entities — separate domain model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Role labels -> canonical bucket (open vocabulary: the label itself is stored raw).
ORG_LABELS = {
    "GENPROJECT": re.compile(r"ген(?:еральн\w*\s+)?проектировщик", re.IGNORECASE),
    "PROJECT_ORG": re.compile(r"проектн\w+\s+организац|проектировщик", re.IGNORECASE),
    "CUSTOMER": re.compile(r"заказчик", re.IGNORECASE),
    "CONTRACTOR": re.compile(r"подрядчик|генподрядчик|исполнител", re.IGNORECASE),
    "DEVELOPER": re.compile(r"разработчик|разработано", re.IGNORECASE),
}

PERSON_LABELS = {
    "GIP": re.compile(r"\bгип\b|главн\w*\s+инженер\w*\s+проект", re.IGNORECASE),
    "GAP": re.compile(r"\bгап\b|главн\w*\s+архитектор\w*\s+проект", re.IGNORECASE),
    "DIRECTOR": re.compile(r"генеральн\w*\s+директор|директор", re.IGNORECASE),
    "CHIEF_ENGINEER": re.compile(r"главн\w*\s+инженер", re.IGNORECASE),
    "CHIEF_SPECIALIST": re.compile(r"главн\w*\s+специалист", re.IGNORECASE),
    "DEPARTMENT_HEAD": re.compile(r"начальник\w*\s+отдел", re.IGNORECASE),
    "GROUP_LEAD": re.compile(r"руководител\w*\s+(групп|проект)", re.IGNORECASE),
    "DEVELOPED": re.compile(r"разработал|выполнил", re.IGNORECASE),
    "CHECKED": re.compile(r"проверил", re.IGNORECASE),
    "APPROVED": re.compile(r"согласовал|утвердил", re.IGNORECASE),
    "NORM_CONTROL": re.compile(r"нормоконтрол", re.IGNORECASE),
}

#: "Иванов И.И." / "И.И. Иванов" / "Иванов Иван Иванович"
NAME_PATTERNS = (
    re.compile(r"[А-ЯЁ][а-яё\-]{2,}\s+[А-ЯЁ]\.\s*[А-ЯЁ]\."),
    re.compile(r"[А-ЯЁ]\.\s*[А-ЯЁ]\.\s*[А-ЯЁ][а-яё\-]{2,}"),
    re.compile(r"[А-ЯЁ][а-яё\-]{2,}\s+[А-ЯЁ][а-яё\-]{2,}\s+[А-ЯЁ][а-яё\-]{2,}"),
)

#: ООО/АО/ПАО/ГБУ/ГКУ/МУП/ФГУП + name, or a quoted name.
ORG_PATTERNS = (
    re.compile(r"(?:ООО|ОАО|ЗАО|ПАО|АО|ГБУ|ГКУ|ГАУ|МУП|ГУП|ФГУП|АНО|ИП)\s*[«\"][^»\"]{2,80}[»\"]"),
    re.compile(r"[«\"][^»\"]{3,80}(?:проект|институт|компани|групп|бюро)[^»\"]{0,40}[»\"]", re.IGNORECASE),
)


@dataclass
class MetadataHit:
    kind: str            # ORGANIZATION | PERSON
    role_bucket: str     # canonical bucket (raw label kept in source_quote)
    raw_value: str
    source_quote: str
    page_or_sheet: Optional[str] = None
    section_code: Optional[str] = None


def _first(pattern_group, text: str) -> Optional[tuple]:
    for bucket, rx in pattern_group.items():
        for match in rx.finditer(text):
            tail = text[match.end():]
            for name_rx in NAME_PATTERNS:
                found = name_rx.search(tail)
                if found:
                    return bucket, found.group(0)
            for org_rx in ORG_PATTERNS:
                found = org_rx.search(tail)
                if found:
                    return bucket, found.group(0)
    return None


def scan_lines(lines: List[str], *, page: Optional[str] = None) -> List[MetadataHit]:
    """Find explicit organization/person statements in title-page/signature lines."""
    hits: List[MetadataHit] = []
    for raw_line in lines:
        line = " ".join(str(raw_line or "").split())
        if len(line) < 5:
            continue
        person = _first(PERSON_LABELS, line)
        if person:
            hits.append(MetadataHit("PERSON", person[0], person[1], line, page))
            continue
        org = _first(ORG_LABELS, line)
        if org:
            hits.append(MetadataHit("ORGANIZATION", org[0], org[1], line, page))
    return hits
