"""RETRIEVAL PROVENANCE (WIP point 0).

A raw document match is only trustworthy when the stored record lets us replay
the matcher decision on the exact span that produced it. This module turns an
enriched matcher result into the provenance record persisted on
``document_match_details``:

``rule_term``
    Taxonomy label / rule that triggered the match (legacy ``matched_term``).
``matched_text``
    Literal document text the matcher actually scored (cell text for tables,
    raw line for text, merged raw text for merged-line fuzzy matches).
``source_span``
    Raw document slice the match was localised to, with ``char_start``/
    ``char_end`` offsets into the parsed text.
``provenance_status``
    ``VERIFIED`` (decision replayed on the stored span), ``INVALID`` (cannot be
    localised/replayed) or ``LEGACY_UNVERIFIED`` (written before this contract).

Fail-closed policy: anything that cannot be reproduced is ``INVALID`` and must
not reach semantic validation / structured extraction. Pre-existing rows are
backfilled to ``LEGACY_UNVERIFIED`` by the migration, never to ``VERIFIED``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rapidfuzz import fuzz

from document_processor.matching.normalization import normalize_ocr_line

VERIFIED = "VERIFIED"
INVALID = "INVALID"
LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"
VALID_STATUSES = (VERIFIED, INVALID, LEGACY_UNVERIFIED)

_WS_RE = re.compile(r"\s+")
_WORD_CHAR = "0-9a-zA-Z\u0430-\u044f\u0451"
_BOUNDARY_LEFT = r"(?:^|\s|[^" + _WORD_CHAR + r"])"
_BOUNDARY_RIGHT = r"(?:$|\s|[^" + _WORD_CHAR + r"])"


def normalize_text(value: Any) -> str:
    """OCR-normalised, case-folded, whitespace-collapsed comparison form."""
    text = normalize_ocr_line(str(value or "").lower())
    return _WS_RE.sub(" ", text).strip()


def _raw_lower(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "").lower()).strip()


def _column_index_from_letter(value: Any) -> Optional[int]:
    letter = str(value or "").strip().upper()
    if not letter or not letter.isalpha():
        return None
    index = 0
    for ch in letter:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def _line_offsets(text: str) -> List[Tuple[int, int]]:
    """(start, end) offsets per ``text.splitlines()`` line, end excludes EOL."""
    offsets: List[Tuple[int, int]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        content_end = pos + len(line.rstrip("\r\n"))
        offsets.append((pos, content_end))
        pos += len(line)
    if not offsets and text:
        offsets.append((0, len(text)))
    return offsets


def _span_from_lines(
    text: str,
    offsets: Sequence[Tuple[int, int]],
    start_line: Optional[int],
    end_line: Optional[int],
) -> Tuple[Optional[int], Optional[int], str]:
    if not start_line or start_line < 1:
        return None, None, ""
    last = end_line if end_line and end_line >= start_line else start_line
    if last > len(offsets):
        return None, None, ""
    char_start = offsets[start_line - 1][0]
    char_end = offsets[last - 1][1]
    if char_end < char_start:
        return None, None, ""
    return char_start, char_end, text[char_start:char_end]


def _boundary_hit(term: str, haystack: str) -> bool:
    if not term or not haystack:
        return False
    pattern = _BOUNDARY_LEFT + re.escape(term) + _BOUNDARY_RIGHT
    return re.search(pattern, haystack) is not None


def _word_coverage(rule_text: str, haystack: str) -> float:
    words = [w for w in rule_text.split() if len(w) >= 2 and any(ch.isalpha() for ch in w)]
    if not words:
        words = [w for w in rule_text.split() if len(w) >= 3 and not w.isdigit()]
    if not words:
        return 0.0
    present = 0
    for word in words:
        if word in haystack:
            present += 1
            continue
        stem = word[: max(4, int(len(word) * 0.7))]
        if stem and stem in haystack:
            present += 1
    return present / len(words)


def _fuzzy_replay_matches(rule_raw: str, rule_norm: str, method: str, target: str, score: float) -> bool:
    """Replays the recorded fuzzy scorer (not the best of all scorers).

    The matcher labels both ``partial_ratio`` and ``token_set_ratio`` results as
    ``FUZZY_TOKEN_SET``, so replay accepts either for that label but never a
    scorer from a different method.
    """
    if method == "FUZZY_RATIO":
        scorers = (fuzz.ratio,)
    else:  # FUZZY_TOKEN_SET
        scorers = (fuzz.partial_ratio, fuzz.token_set_ratio)
    targets = {target, target.lower(), normalize_text(target)}
    for keyword in {rule_raw, rule_norm}:
        if not keyword:
            continue
        for text in targets:
            if not text:
                continue
            for scorer in scorers:
                if abs(int(scorer(keyword, text)) - float(score)) <= 1.0:
                    return True
    return False


def _replay(
    *,
    rule_raw: str,
    rule_norm: str,
    method: str,
    score: float,
    matched_text: str,
    source_span: str,
    min_score: int,
) -> Tuple[bool, str]:
    """Replays the recorded matcher method on the stored span."""
    matched_norm = normalize_text(matched_text)
    span_norm = normalize_text(source_span)
    method = method.upper()

    if method == "EXACT":
        ok = _boundary_hit(rule_norm, matched_norm) or _boundary_hit(rule_norm, span_norm)
        return ok, "EXACT_BOUNDARY_REPLAY"

    if method in ("FUZZY_RATIO", "FUZZY_TOKEN_SET"):
        if not rule_norm or not matched_norm:
            return False, "FUZZY_WITHOUT_TERM"
        ok = _fuzzy_replay_matches(rule_raw, rule_norm, method, matched_text, score)
        return ok, "FUZZY_SCORE_REPLAY"

    if method == "STEM_PREFIX":
        coverage = _word_coverage(rule_norm, matched_norm)
        return coverage >= 0.7 and float(score) >= float(min_score), "STEM_COVERAGE_REPLAY"

    if method == "COMPOUND_RULE":
        # Decision is a conjunction over the span; the exact predicate lives in
        # composite_drainage_rule and is re-checked by re-running it upstream.
        from document_processor.matching.composite_drainage_rule import (
            match_composite_drainage,
        )

        try:
            reproduced = bool(match_composite_drainage([source_span or matched_text]))
        except Exception:
            reproduced = False
        return reproduced, "COMPOUND_PREDICATE_REPLAY"

    return False, "UNREPLAYABLE_METHOD"


def build_provenance(
    match: Dict[str, Any],
    document_text: str,
    *,
    min_score: int = 0,
) -> Dict[str, Any]:
    """Builds the fail-closed provenance record for one matcher result."""
    rule_term = str(match.get("keyword") or "").strip()
    method = str(match.get("match_method") or "UNKNOWN")
    score = match.get("score") or 0

    matched_text = str(match.get("_matched_text") or match.get("matched_line") or "").strip()
    start_line = match.get("_source_line_start")
    end_line = match.get("_source_line_end")
    offsets = _line_offsets(document_text)
    char_start, char_end, source_span = _span_from_lines(
        document_text, offsets, start_line, end_line
    )

    row_data = match.get("row_data") if isinstance(match.get("row_data"), dict) else {}
    raw_cells = [
        str(cell.get("text", ""))
        for cell in (row_data.get("raw_cells") or [])
        if isinstance(cell, dict)
    ]

    record: Dict[str, Any] = {
        "rule_term": rule_term or None,
        "matched_text": matched_text or None,
        "matched_text_normalized": normalize_text(matched_text) or None,
        "source_span": source_span or matched_text or None,
        "char_start": char_start,
        "char_end": char_end,
        "table_index": match.get("table_index"),
        "source_row_index": match.get("row_index"),
        "source_col_index": match.get("column_index")
        if match.get("column_index") is not None
        else _column_index_from_letter(match.get("column_letter")),
        "column_letter": match.get("column_letter"),
        "cell_address": match.get("cell_address"),
        "provenance_method": None,
        "provenance_reason": None,
        "provenance_status": INVALID,
    }

    def fail(reason: str) -> Dict[str, Any]:
        record["provenance_status"] = INVALID
        record["provenance_reason"] = reason
        return record

    if not rule_term:
        return fail("rule_term_missing")
    if not matched_text:
        return fail("matched_text_missing")
    if char_start is None or char_end is None or not source_span:
        return fail("source_span_unlocalized")

    matched_norm = normalize_text(matched_text)
    span_norm = normalize_text(source_span)
    if matched_norm and matched_norm not in span_norm:
        return fail("matched_text_not_in_source_span")

    if raw_cells and method.upper() != "COMPOUND_RULE":
        joined = normalize_text(" ".join(raw_cells))
        if matched_norm and matched_norm not in joined:
            return fail("row_data_span_mismatch")

    ok, replay_method = _replay(
        rule_raw=str(rule_term).lower().strip(),
        rule_norm=normalize_text(rule_term),
        method=method,
        score=score,
        matched_text=matched_text,
        source_span=source_span,
        min_score=min_score,
    )
    record["provenance_method"] = replay_method
    if not ok:
        return fail("decision_not_reproducible")

    record["provenance_status"] = VERIFIED
    record["provenance_reason"] = "matcher_decision_reproduced"
    return record
