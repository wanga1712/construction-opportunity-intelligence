"""RETRIEVAL PROVENANCE (WIP point 0) contract tests.

A raw match is VERIFIED only when the stored span lets us replay the matcher
decision; anything unlocalised / unreplayable is INVALID and must not reach
semantic validation or structured extraction.
"""

import os
import sys

tender_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tender_documents_research"))
if tender_dir not in sys.path:
    sys.path.insert(0, tender_dir)

from rapidfuzz import fuzz  # noqa: E402

from document_processor.match_engine import MatchEngine  # noqa: E402
from document_processor.matching.provenance import (  # noqa: E402
    INVALID,
    LEGACY_UNVERIFIED,
    VALID_STATUSES,
    VERIFIED,
    build_provenance,
    normalize_text,
)

TEXT = (
    "1  \u041d\u043e\u0443\u0442\u0431\u0443\u043a Lenovo 16 \u0413\u0411\n"
    "2  \u041f\u0440\u043e\u043c\u044b\u0448\u043b\u0435\u043d\u043d\u044b\u0439 \u043f\u043e\u043b 100 \u043c2\n"
    "3  \u041b\u043e\u0442\u043e\u043a \u0432\u043e\u0434\u043e\u043e\u0442\u0432\u043e\u0434\u043d\u044b\u0439 \u043b\u0438\u043d\u0435\u0439\u043d\u044b\u0439 "
    "\u0438\u0437 \u043f\u043e\u043b\u0438\u043c\u0435\u0440\u043d\u043e\u0433\u043e \u043a\u043e\u043c\u043f\u043e\u0437\u0438\u0442\u043d\u043e\u0433\u043e \u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b\u0430\n"
)


def test_valid_status_vocabulary_is_fail_closed():
    assert VALID_STATUSES == (VERIFIED, INVALID, LEGACY_UNVERIFIED)


def test_exact_table_cell_match_is_verified():
    text = "1\t\u041d\u043e\u0443\u0442\u0431\u0443\u043a Lenovo 16 \u0413\u0411\n"
    meta = {
        1: {
            "table_index": 1,
            "page_number": 1,
            "cells": [
                {"text": "1", "column_letter": "A", "cell_address": "A2"},
                {
                    "text": "\u041d\u043e\u0443\u0442\u0431\u0443\u043a Lenovo 16 \u0413\u0411",
                    "column_letter": "B",
                    "cell_address": "B2",
                },
            ],
        }
    }
    engine = MatchEngine(keywords=["\u043d\u043e\u0443\u0442\u0431\u0443\u043a"], min_score=75)
    details = engine.process_text(text, meta)

    assert len(details) == 1
    prov = details[0].provenance
    assert prov["provenance_status"] == VERIFIED
    assert prov["rule_term"] == "\u043d\u043e\u0443\u0442\u0431\u0443\u043a"
    assert prov["matched_text"] == "\u041d\u043e\u0443\u0442\u0431\u0443\u043a Lenovo 16 \u0413\u0411"
    assert prov["char_start"] == 0 and prov["char_end"] == len(text.rstrip("\n"))
    assert details[0].page_or_sheet == "1"
    assert details[0].row_number == 1


def test_fuzzy_line_replays_on_stored_span():
    line = "\u041f\u0440\u043e\u043c\u044b\u0448\u043b\u0435\u043d\u043d\u044b\u0439 \u043f\u043e\u043b 100 \u043c2"
    keyword = "\u043f\u0440\u043e\u043c\u044b\u0448\u043b\u0435\u043d\u043d\u044b\u0439 \u043f\u043e\u043b"
    score = int(fuzz.token_set_ratio(keyword, normalize_text(line)))
    record = build_provenance(
        {
            "keyword": keyword,
            "match_method": "FUZZY_TOKEN_SET",
            "score": score,
            "line_number": 2,
            "_matched_text": line,
            "_source_line_start": 2,
            "_source_line_end": 2,
            "row_data": {"values": {"text": line}},
        },
        TEXT,
        min_score=75,
    )
    assert record["provenance_status"] == VERIFIED
    assert record["provenance_method"] == "FUZZY_SCORE_REPLAY"


def test_unlocalized_match_is_invalid():
    record = build_provenance(
        {
            "keyword": "\u043d\u043e\u0443\u0442\u0431\u0443\u043a",
            "match_method": "EXACT",
            "score": 100,
            "_matched_text": "\u041d\u043e\u0443\u0442\u0431\u0443\u043a Lenovo 16 \u0413\u0411",
            "_source_line_start": None,
            "_source_line_end": None,
            "row_data": {},
        },
        TEXT,
    )
    assert record["provenance_status"] == INVALID
    assert record["provenance_reason"] == "source_span_unlocalized"


def test_matched_text_outside_stored_span_is_invalid():
    record = build_provenance(
        {
            "keyword": "\u043f\u0440\u043e\u043c\u044b\u0448\u043b\u0435\u043d\u043d\u044b\u0439 \u043f\u043e\u043b",
            "match_method": "FUZZY_TOKEN_SET",
            "score": 100,
            "_matched_text": "\u041f\u0440\u043e\u043c\u044b\u0448\u043b\u0435\u043d\u043d\u044b\u0439 \u043f\u043e\u043b 100 \u043c2",
            "_source_line_start": 1,
            "_source_line_end": 1,
            "row_data": {},
        },
        TEXT,
    )
    assert record["provenance_status"] == INVALID
    assert record["provenance_reason"] == "matched_text_not_in_source_span"


def test_compound_rule_replays_predicate_on_span():
    line = (
        "\u041b\u043e\u0442\u043e\u043a \u0432\u043e\u0434\u043e\u043e\u0442\u0432\u043e\u0434\u043d\u044b\u0439 \u043b\u0438\u043d\u0435\u0439\u043d\u044b\u0439 "
        "\u0438\u0437 \u043f\u043e\u043b\u0438\u043c\u0435\u0440\u043d\u043e\u0433\u043e \u043a\u043e\u043c\u043f\u043e\u0437\u0438\u0442\u043d\u043e\u0433\u043e \u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b\u0430"
    )
    record = build_provenance(
        {
            "keyword": "\u041a\u043e\u043c\u043f\u043e\u0437\u0438\u0442\u043d\u044b\u0439 \u0432\u043e\u0434\u043e\u043e\u0442\u0432\u043e\u0434\u043d\u044b\u0439 \u043b\u043e\u0442\u043e\u043a",
            "match_method": "COMPOUND_RULE",
            "score": 100,
            "_matched_text": line,
            "_source_line_start": 3,
            "_source_line_end": 3,
            "row_data": {},
        },
        TEXT,
    )
    assert record["provenance_status"] == VERIFIED
    assert record["provenance_method"] == "COMPOUND_PREDICATE_REPLAY"
