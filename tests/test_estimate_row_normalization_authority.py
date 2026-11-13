import sys
from pathlib import Path


RESEARCH_ROOT = Path(__file__).resolve().parents[1] / "tender_documents_research"
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))


from document_processor.estimate_row_normalization_authority import (  # noqa: E402
    RowsetSignature,
    normalization_state,
)


VERSION = "estimate_row_taxonomy_resolver_v1"


def _signature(count=10, max_id=100, digest="abc"):
    return RowsetSignature(row_count=count, max_row_id=max_id, sha256=digest)


def _coverage(**overrides):
    value = {
        "normalizer_version": VERSION,
        "coverage_complete": True,
        "status": "COMPLETED",
        "input_row_count": 10,
        "input_max_row_id": 100,
        "input_rows_sha256": "abc",
    }
    value.update(overrides)
    return value


def test_completed_coverage_is_completed():
    assert normalization_state(current=_signature(), coverage=_coverage()) == "COMPLETED"


def test_partial_coverage_is_partial():
    coverage = _coverage(coverage_complete=False, status="PARTIAL")
    assert normalization_state(current=_signature(), coverage=coverage) == "PARTIAL"


def test_new_rows_after_completion_are_stale():
    assert normalization_state(
        current=_signature(count=11, max_id=101, digest="new"),
        coverage=_coverage(),
    ) == "STALE"


def test_new_normalizer_version_requires_rerun():
    assert normalization_state(
        current=_signature(),
        coverage=_coverage(),
        version="estimate_row_taxonomy_resolver_v2",
    ) == "NOT_PROVEN_FOR_VERSION"


def test_category_without_marker_is_not_proven_normalized():
    assert normalization_state(current=_signature(), coverage=None) == "NOT_PROVEN_NORMALIZED"


def test_zero_match_with_all_rows_examined_is_valid_completed():
    coverage = _coverage(rows_matched=0, rows_unmatched=10)
    assert normalization_state(current=_signature(), coverage=coverage) == "COMPLETED"


def test_dry_run_coverage_is_not_treated_as_completed():
    coverage = _coverage(status="DRY_RUN")
    assert normalization_state(current=_signature(), coverage=coverage) == "DRY_RUN"
