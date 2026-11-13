from src.services.commercial_routing_v3.reconciliation_document_plan import (
    plan_queue_status,
)


def _plan(*, docs=True, allowed=True, action="DOCUMENT_RESEARCH_REQUIRED"):
    return {
        "selected_source_document_ids": [10] if docs else [],
        "acquisition_allowed": allowed,
        "research_action_v2": action,
    }


def test_research_plan_is_claimable_waiting_status():
    assert plan_queue_status(_plan()) == "PRE_RESEARCH_WAITING"


def test_no_document_research_is_not_left_pending():
    assert plan_queue_status(_plan(action="NO_DOCUMENT_RESEARCH")) == "SKIPPED_NOT_TARGET"


def test_missing_documents_is_terminal_no_links():
    assert plan_queue_status(_plan(docs=False)) == "NO_LINKS"
