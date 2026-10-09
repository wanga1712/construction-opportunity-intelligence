"""Focused tests: category amount split (НМЦК vs document-confirmed category value)."""
from __future__ import annotations


def _helpers():
    from src.ui.analytics_contour_v2_page import _document_category_value, _fmt_doc_category_value
    return _document_category_value, _fmt_doc_category_value


def test_control_1061_no_document_value_never_falls_back_to_nmck():
    doc_value, fmt = _helpers()
    row = {"initial_price": 440112094.85, "expected_category_value": None,
           "category_value_basis": "UNKNOWN_ADDRESSABLE_VALUE"}
    assert doc_value(row) is None
    assert fmt(row) == "—"          # NOT 440 112 094,85


def test_document_value_present_is_shown():
    doc_value, fmt = _helpers()
    row = {"initial_price": 440112094.85, "expected_category_value": 12450000,
           "category_value_basis": "DOCUMENT_EXPLICIT_TOTAL"}
    assert doc_value(row) == 12450000
    assert fmt(row) != "—"


def test_non_document_basis_is_not_shown_as_document_value():
    doc_value, fmt = _helpers()
    row = {"initial_price": 1000000, "expected_category_value": 1000000,
           "category_value_basis": "DIRECT_SINGLE_CATEGORY_PROCUREMENT_VALUE"}
    assert doc_value(row) is None   # only DOCUMENT_* bases count as document-confirmed
    assert fmt(row) == "—"
