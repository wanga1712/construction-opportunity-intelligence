import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = ROOT / "tender_documents_research"
for path in (ROOT, RESEARCH_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from tender_documents_research.document_processor.embedded_persistence import (  # noqa: E402
    CATEGORY_FACTS_NOT_RESOLVED,
    FACTS_FOUND,
    FACTS_OUTSIDE_ALLOWED_SCOPE,
    NO_RAW_FACTS,
    PERSISTENCE_FAILED,
    PersistenceResult,
    RAW_FACTS_FILTERED,
)


def test_extracted_and_persisted_is_facts_found():
    result = PersistenceResult(
        extracted_facts=2,
        accepted_facts=2,
        created=2,
    )

    assert result.outcome == FACTS_FOUND
    assert result.persisted_facts == 2


def test_zero_raw_facts_is_no_raw_facts():
    result = PersistenceResult(extracted_facts=0)

    assert result.outcome == NO_RAW_FACTS


def test_raw_facts_rejected_by_goods_gate_is_not_no_raw_facts():
    result = PersistenceResult(
        extracted_facts=10,
        goods_accepted_facts=0,
        accepted_facts=0,
    )

    assert result.outcome == RAW_FACTS_FILTERED
    assert result.outcome != NO_RAW_FACTS


def test_goods_accepted_without_category_is_category_not_resolved():
    result = PersistenceResult(
        extracted_facts=10,
        goods_accepted_facts=10,
        category_resolved_facts=0,
        accepted_facts=0,
    )

    assert result.outcome == CATEGORY_FACTS_NOT_RESOLVED


def test_all_facts_outside_allowed_categories_is_explicit():
    result = PersistenceResult(
        extracted_facts=10,
        goods_accepted_facts=10,
        category_resolved_facts=10,
        allowed_rejected_facts=10,
        accepted_facts=0,
    )

    assert result.outcome == FACTS_OUTSIDE_ALLOWED_SCOPE


def test_persistence_exception_is_not_facts_found():
    result = PersistenceResult(
        extracted_facts=2,
        accepted_facts=2,
        error="OperationalError: transaction failed",
    )

    assert result.outcome == PERSISTENCE_FAILED
    assert result.outcome != FACTS_FOUND


def test_accepted_with_zero_persisted_is_not_success():
    result = PersistenceResult(
        extracted_facts=2,
        accepted_facts=2,
        created=0,
        reused=0,
    )

    assert result.outcome == PERSISTENCE_FAILED


def test_reused_idempotent_entity_is_success():
    result = PersistenceResult(
        extracted_facts=2,
        accepted_facts=2,
        created=0,
        reused=2,
    )

    assert result.outcome == FACTS_FOUND
    assert result.persisted_facts == 2
