"""EMBEDDED_ESTIMATE_PARSE_FIRST_V1 — сравнение раздела сметы с закупкой.

Детерминированное сравнение названия раздела/объекта из сметы с названием
закупки, ОКПД и (если есть) object classification. Ничего не пишет.

Возвращает:
  MATCHED   — есть содержательное пересечение;
  PARTIAL   — пересечение слабое (одно общее слово);
  NO_MATCH  — содержательных общих слов нет;
  NO_DATA   — нечего сравнивать.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence

MATCHED = "MATCHED"
PARTIAL = "PARTIAL"
NO_MATCH = "NO_MATCH"
NO_DATA = "NO_DATA"

_STOPWORDS = {
    "и", "или", "на", "по", "для", "с", "со", "в", "во", "из", "от", "до",
    "объект", "объекта", "объекты", "строительство", "строительства",
    "реконструкция", "реконструкции", "ремонт", "ремонта", "работы", "работ",
    "услуги", "закупка", "закупки", "поставка", "поставки", "выполнение",
    "устройство", "монтаж", "капитальный", "текущий", "шт", "м", "м2", "м3",
}
_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def _normalize(text: Any) -> str:
    return str(text or "").lower().replace("ё", "е")


def meaningful_tokens(*texts: Any) -> List[str]:
    out: List[str] = []
    for text in texts:
        for tok in _TOKEN_RE.findall(_normalize(text)):
            if len(tok) < 4 or tok in _STOPWORDS:
                continue
            if tok not in out:
                out.append(tok)
    return out


def _stem(token: str) -> str:
    """Грубый стем: первые 4 символа — покрывает дорог/дорожная, свет/светильник."""
    return token[:4]


def compare_section_to_procurement(
    section_name: Any,
    *,
    procurement_title: Any = None,
    okpd_name: Any = None,
    object_class: Any = None,
) -> Dict[str, Any]:
    """Сравнить название раздела с контекстом закупки."""
    section_tokens = meaningful_tokens(section_name)
    context_tokens = meaningful_tokens(procurement_title, okpd_name, object_class)
    if not section_tokens or not context_tokens:
        return {"state": NO_DATA, "overlap": [], "score": 0.0}
    ctx_stems = {_stem(t) for t in context_tokens}
    overlap = [t for t in section_tokens if _stem(t) in ctx_stems]
    if not overlap:
        # substring containment (e.g. «светильник» vs «светильники»)
        overlap = [
            t for t in section_tokens
            if any(t[:5] in c or c[:5] in t for c in context_tokens)
        ]
    if not overlap:
        return {"state": NO_MATCH, "overlap": [], "score": 0.0}
    score = round(len(overlap) / max(1, len(section_tokens)), 3)
    return {
        "state": MATCHED if len(overlap) >= 2 or score >= 0.5 else PARTIAL,
        "overlap": overlap[:8],
        "score": score,
    }


def compare_sections(
    sections: Sequence[Dict[str, Any]],
    *,
    procurement_title: Any = None,
    okpd_name: Any = None,
    object_class: Any = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in sections or []:
        result = compare_section_to_procurement(
            s.get("section_name") or s.get("section_code"),
            procurement_title=procurement_title,
            okpd_name=okpd_name,
            object_class=object_class,
        )
        out.append({
            "section_code": s.get("section_code"),
            "section_name": s.get("section_name"),
            **result,
        })
    return out
