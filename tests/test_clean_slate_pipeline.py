"""Tests for CRM-V3-CLEAN-SLATE-ACTUAL-PIPELINE-BUILD-1.

Covers:
- queue_producer: AI_QUEUE_ADMISSION_GATE=NO (no NO_COMMERCIAL_ENTRY/SKIP/WOOD gates)
- evidence_discovery: EVIDENCE_DISCOVERY_PERFORMS_LEXICAL_SEARCH=NO, real vocab
- learning_observer: manifest from resolve_document_links, NOT document_files
"""

import json
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# queue_producer: AI_QUEUE_ADMISSION_GATE=NO
# ---------------------------------------------------------------------------

def test_decide_from_normalized_no_commercial_entry_allowed():
    """NO_COMMERCIAL_ENTRY must NOT gate decide_from_normalized.

    AI_QUEUE_ADMISSION_GATE=NO: the model's empty_hypothesis_status
    must never block routing decisions entirely in the legacy flow.
    """
    from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer

    prod = CommercialRoutingV3QueueProducer.__new__(CommercialRoutingV3QueueProducer)

    # With valid hypotheses, decision is always produced regardless of empty_hypothesis_status
    normalized = {
        "empty_hypothesis_status": "NO_COMMERCIAL_ENTRY",
        "commercial_category_hypotheses": [
            {
                "research_action": "DEEP_RESEARCH",
                "category_code": "lighting",
                "candidate_medal": "GOLD",
                "opportunity_track": "DIRECT_SUPPLY",
            }
        ],
    }
    decision = prod.decide_from_normalized(normalized)
    # AI gate removed: decision is returned (not None)
    assert decision is not None, "AI_QUEUE_ADMISSION_GATE=NO: must not return None for NO_COMMERCIAL_ENTRY"
    assert decision["research_action"] == "DEEP_RESEARCH"


def test_populate_all_eligible_method_exists():
    """CommercialRoutingV3QueueProducer must have populate_all_eligible()."""
    from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer
    assert hasattr(CommercialRoutingV3QueueProducer, "populate_all_eligible"), (
        "populate_all_eligible() method missing — exhaustive queuing not implemented"
    )


def test_populate_all_eligible_dry_run():
    """populate_all_eligible dry_run=True must never touch document DB."""
    from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer

    mock_crm_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = [
        {
            "id": 100, "source_table": "fz44_lots", "source_id": 1,
            "contract_number": "12345", "end_date": None,
            "crm_stage": "active", "award_status": None,
        }
    ]
    mock_crm_conn.cursor.return_value = mock_cursor
    mock_crm_conn.autocommit = True

    prod = CommercialRoutingV3QueueProducer.__new__(CommercialRoutingV3QueueProducer)
    prod._crm_dsn = {}
    prod._doc_dsn = {}

    with patch("psycopg2.connect") as mock_connect:
            # First connect = CRM, second call sequence handled per-loop iteration
            call_count = [0]
            def side_effect(**kwargs):
                call_count[0] += 1
                conn = MagicMock()
                conn.autocommit = True
                cursor = MagicMock()
                cursor.__enter__ = MagicMock(return_value=cursor)
                cursor.__exit__ = MagicMock(return_value=False)
                if call_count[0] == 1:
                    # First batch returns 1 row, second returns empty
                    call_returns = [
                        [{"id": 1, "source_table": "fz44_lots", "source_id": 1,
                          "contract_number": "12345", "end_date": None,
                          "crm_stage": "active", "award_status": None}],
                        [],
                    ]
                    cursor.fetchall.side_effect = call_returns
                conn.cursor.return_value = cursor
                return conn

            mock_connect.side_effect = side_effect

            with patch(
                "src.services.commercial_routing_v3.document_links.count_document_links",
                return_value=3,
            ):
                result = prod.populate_all_eligible(dry_run=True)

    assert result["dry_run"] is True
    assert result["AI_QUEUE_ADMISSION_GATE"] == "NO"
    assert result["STOPWORD_QUEUE_ADMISSION_GATE"] == "NO"


# ---------------------------------------------------------------------------
# evidence_discovery: EVIDENCE_DISCOVERY_PERFORMS_LEXICAL_SEARCH=NO
# ---------------------------------------------------------------------------

def test_evidence_discovery_no_lexical_search():
    """evidence_discovery must NOT perform lexical document scanning.

    EVIDENCE_DISCOVERY_PERFORMS_LEXICAL_SEARCH=NO.
    discover_and_persist_raw_evidence delegates to bridge_match_details.
    """
    from src.services.commercial_routing_v3.evidence_discovery import (
        discover_and_persist_raw_evidence,
        bridge_match_details_to_evidence,
    )
    # discover_and_persist_raw_evidence must call bridge_match_details_to_evidence
    # (not iter_parsed_units directly)
    import inspect
    src = inspect.getsource(discover_and_persist_raw_evidence)
    assert "bridge_match_details_to_evidence" in src, (
        "evidence_discovery still does its own lexical scanning — must delegate to bridge"
    )
    assert "iter_parsed_units" not in src, (
        "evidence_discovery must NOT call iter_parsed_units — lexical scan forbidden"
    )


def test_evidence_discovery_vocabulary_uses_real_phrases():
    """load_discovery_vocabulary must query crm_product_subcategory_terms.

    VOCABULARY_AUTHORITY = crm_product_subcategory_terms.term_type='search'
    Must NOT use category names or subcategory names as vocabulary.
    """
    from src.services.commercial_routing_v3.evidence_discovery import load_discovery_vocabulary
    import inspect
    src = inspect.getsource(load_discovery_vocabulary)
    assert "crm_product_subcategory_terms" in src, (
        "load_discovery_vocabulary must use crm_product_subcategory_terms (real phrase registry)"
    )
    assert "CATEGORY_NAME_MATCH" not in src, (
        "load_discovery_vocabulary must not use category names as vocabulary"
    )
    assert "SUBCATEGORY_NAME_MATCH" not in src, (
        "load_discovery_vocabulary must not use subcategory names as vocabulary"
    )


def test_evidence_discovery_method_is_bridge():
    """evidence_hash must reflect discovery_method=BRIDGE_FROM_MATCH_DETAILS.

    EVIDENCE_DISCOVERY_PERFORMS_LEXICAL_SEARCH=NO.
    """
    from src.services.commercial_routing_v3.evidence_discovery import bridge_match_details_to_evidence
    import inspect
    src = inspect.getsource(bridge_match_details_to_evidence)
    assert "BRIDGE_FROM_MATCH_DETAILS" in src
    assert "document_match_details" in src


# ---------------------------------------------------------------------------
# learning_observer: manifest from resolve_document_links
# ---------------------------------------------------------------------------

def test_learning_observer_manifest_from_resolve_document_links():
    """_resolve_document_manifest must call resolve_document_links, NOT query document_files.

    Step 6 requirement: MANIFEST_AUTHORITY = resolve_document_links(S7).
    """
    from src.services.commercial_routing_v3.learning_observer import LearningObserver
    import inspect
    src = inspect.getsource(LearningObserver._resolve_document_manifest)
    assert "resolve_document_links" in src, (
        "learning_observer._resolve_document_manifest must call resolve_document_links"
    )
    # document_files must NOT appear as a DB query (not in FROM clause)
    assert "FROM document_files" not in src, (
        "learning_observer._resolve_document_manifest must NOT query document_files table"
    )
    # Must not use psycopg2 directly in the manifest builder (no direct DB)
    assert "psycopg2.connect" not in src, (
        "learning_observer._resolve_document_manifest must not open its own DB connection"
    )


def test_learning_observer_snapshot_builder_uses_manifest():
    """_build_missing_snapshots must call _resolve_document_manifest."""
    from src.services.commercial_routing_v3.learning_observer import LearningObserver
    import inspect
    src = inspect.getsource(LearningObserver._build_missing_snapshots)
    # Must call _resolve_document_manifest, not document_files directly
    assert "_resolve_document_manifest" in src, (
        "_build_missing_snapshots must delegate to _resolve_document_manifest"
    )
    assert "FROM document_files" not in src, (
        "_build_missing_snapshots must not query document_files directly for manifest"
    )


def test_evidence_hash_is_deterministic():
    """compute_evidence_hash must be deterministic."""
    from src.services.commercial_routing_v3.evidence_discovery import compute_evidence_hash
    h1 = compute_evidence_hash("освещение", "светодиодный светильник", '{"row": 1}')
    h2 = compute_evidence_hash("освещение", "светодиодный светильник", '{"row": 1}')
    assert h1 == h2
    h3 = compute_evidence_hash("освещение", "другой текст", '{"row": 1}')
    assert h1 != h3


def test_vocabulary_hash_is_deterministic():
    """compute_vocabulary_hash must be deterministic and version-stamped."""
    from src.services.commercial_routing_v3.evidence_discovery import compute_vocabulary_hash
    vocab = [
        {"term": "светодиод", "category_code": "lighting", "weight": 100},
        {"term": "брусчатка", "category_code": "flooring", "weight": 90},
    ]
    v1, h1 = compute_vocabulary_hash(vocab)
    v2, h2 = compute_vocabulary_hash(vocab)
    assert h1 == h2
    assert v1.startswith("v3_vocab_")
    # Different vocab → different hash
    v3, h3 = compute_vocabulary_hash(vocab + [{"term": "extra", "category_code": "x", "weight": 1}])
    assert h3 != h1
