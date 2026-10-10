"""Deterministic normalized-input signal block for the V3 model prompt.

Embeds the normalized title / ``match_key`` plus the active POSITIVE/NEGATIVE
phrase hints so the model sees the same deterministic view the routing rules
use. Hints are advice, NOT a whitelist: the live registry category list and the
evidence contract stay unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, List, Set

from src.services.commercial_routing_v3.text_normalization import (
    canonical_tokens,
    match_key,
    normalize_text,
)

_POSITIVE = "POSITIVE_SIGNAL"
_NEGATIVE = {"NEGATIVE_SIGNAL", "HARD_EXCLUSION"}


def _title_of(procurement: Dict[str, Any]) -> str:
    return str(procurement.get("title") or procurement.get("auction_name") or "")


def _group(signals: List[Dict[str, Any]], wanted: Set[str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for sig in signals or []:
        cat = str(sig.get("commercial_category_code") or "").strip()
        phrase = normalize_text(sig.get("phrase") or "")
        stype = (sig.get("signal_type") or "NEGATIVE_SIGNAL").upper()
        if not cat or not phrase or stype not in wanted:
            continue
        phrases = grouped.setdefault(cat, [])
        if phrase not in phrases:
            phrases.append(phrase)
    return grouped


def _phrase_hits(phrase: str, title_norm: str, title_tokens: List[str]) -> bool:
    """Substring match plus a light stem-prefix match for inflected RU phrases."""
    if not phrase:
        return False
    if phrase in title_norm:
        return True
    head = canonical_tokens(phrase)
    if head and len(head[0]) >= 5:
        return any(token.startswith(head[0]) for token in title_tokens)
    return False


def _render_hints(
    title_norm: str,
    title_tokens: List[str],
    grouped: Dict[str, List[str]],
    *,
    positive: bool,
) -> List[str]:
    lines: List[str] = []
    for cat, phrases in sorted(grouped.items()):
        matched = [p for p in phrases if _phrase_hits(p, title_norm, title_tokens)]
        hit = ", ".join(matched) if matched else "—"
        advice = (
            f"мы видим здесь категорию {cat}"
            if positive
            else f"категорию {cat} не предлагать"
        )
        listed = "», «".join(phrases)
        lines.append(f"- {cat}: «{listed}» [в заголовке: {hit}] → {advice}")
    return lines


def normalized_signal_block(
    procurement: Dict[str, Any],
    routing_signals: List[Dict[str, Any]] | None,
) -> str:
    """Compact deterministic block; ``""`` when there is nothing to add."""
    title = _title_of(procurement)
    title_norm = normalize_text(title)
    key = match_key(title)
    title_tokens = canonical_tokens(title)
    positive = _group(routing_signals or [], {_POSITIVE})
    negative = _group(routing_signals or [], _NEGATIVE)
    if not (title_norm or key or positive or negative):
        return ""
    lines = [
        "NORMALIZED_INPUT_SIGNALS (детерминированная нормализация заголовка; "
        "это подсказки, НЕ whitelist):",
        f"normalized_title: {title_norm or '-'}",
        f"match_key: {key or '-'}",
    ]
    if positive:
        lines.append(
            "POSITIVE phrase hints — «мы видим здесь категорию X» "
            "(подсказка; evidence и контракт category_code всё равно обязательны):"
        )
        lines.extend(_render_hints(title_norm, title_tokens, positive, positive=True))
    if negative:
        lines.append(
            "NEGATIVE phrase hints — «не предлагать» "
            "(если фраза есть в заголовке, эту категорию НЕ предлагать):"
        )
        lines.extend(_render_hints(title_norm, title_tokens, negative, positive=False))
    return "\n".join(lines) + "\n"
