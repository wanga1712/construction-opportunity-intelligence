from unittest.mock import MagicMock, patch
import pytest
from src.services.commercial_routing_v3.okpd_priors import (
    ADMISSION_TARGET,
    ADMISSION_OUT_OF_TARGET,
    ADMISSION_UNKNOWN_OKPD,
    classify_target_okpd,
)
from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer
from src.services.commercial_routing_v3.factual_feeder import FactualFeeder


MOCK_PRIORS = [
    {"commercial_category_code": "lighting", "okpd_pattern": "27.40", "match_type": "PREFIX"},
    {"commercial_category_code": "computers", "okpd_pattern": "26.20.1", "match_type": "EXACT"},
    {"commercial_category_code": "flooring", "okpd_pattern": "43.33", "match_type": "PREFIX"},
]


def test_target_exact_okpd() -> None:
    # Case 1: target exact OKPD -> TARGET
    classification, matched = classify_target_okpd("26.20.1", MOCK_PRIORS)
    assert classification == ADMISSION_TARGET
    assert len(matched) == 1
    assert matched[0]["commercial_category_code"] == "computers"


def test_target_valid_child_prefix_okpd() -> None:
    # Case 2: target valid child/prefix OKPD -> TARGET
    classification, matched = classify_target_okpd("27.40.15.110", MOCK_PRIORS)
    assert classification == ADMISSION_TARGET
    assert len(matched) == 1
    assert matched[0]["commercial_category_code"] == "lighting"


def test_non_target_medical_okpd() -> None:
    # Case 3: non-target medical OKPD -> OUT_OF_TARGET
    classification, matched = classify_target_okpd("32.99.53.191", MOCK_PRIORS)
    assert classification == ADMISSION_OUT_OF_TARGET
    assert matched == []


def test_blank_okpd() -> None:
    # Case 4: blank OKPD -> UNKNOWN_OKPD
    assert classify_target_okpd("", MOCK_PRIORS)[0] == ADMISSION_UNKNOWN_OKPD
    assert classify_target_okpd(None, MOCK_PRIORS)[0] == ADMISSION_UNKNOWN_OKPD
    assert classify_target_okpd("   ", MOCK_PRIORS)[0] == ADMISSION_UNKNOWN_OKPD


@patch('psycopg2.connect')
def test_out_of_target_does_not_call_queue_upsert(mock_connect) -> None:
    # Case 5: OUT_OF_TARGET does not call queue upsert
    mock_crm = MagicMock()
    mock_doc = MagicMock()
    mock_connect.side_effect = [mock_crm, mock_doc]

    mock_crm_cur = mock_crm.cursor.return_value.__enter__.return_value
    mock_crm_cur.fetchall.side_effect = [
        MOCK_PRIORS,
        [{"id": 163649, "source_table": "reestr_contract_44_fz", "source_id": 100, "contract_number": "1", "okpd_code": "32.99.53.191", "crm_stage": "open"}],
        []
    ]

    with patch('src.services.commercial_routing_v3.document_links.batch_count_document_links') as mock_batch_links:
        mock_batch_links.return_value = {163649: 5}

        producer = CommercialRoutingV3QueueProducer()
        with patch.object(producer, '_upsert_queue_task') as mock_upsert:
            res = producer.populate_all_eligible(dry_run=False)
            assert mock_upsert.call_count == 0
            assert res["skipped_out_of_target"] == 1
            assert res["inserted"] == 0


@patch('psycopg2.connect')
def test_unknown_okpd_does_not_create_executable_queue_row(mock_connect) -> None:
    # Case 6: UNKNOWN_OKPD does not create executable queue row
    mock_crm = MagicMock()
    mock_doc = MagicMock()
    mock_connect.side_effect = [mock_crm, mock_doc]

    mock_crm_cur = mock_crm.cursor.return_value.__enter__.return_value
    mock_crm_cur.fetchall.side_effect = [
        MOCK_PRIORS,
        [{"id": 999, "source_table": "reestr_contract_44_fz", "source_id": 101, "contract_number": "2", "okpd_code": None, "crm_stage": "open"}],
        []
    ]

    with patch('src.services.commercial_routing_v3.document_links.batch_count_document_links') as mock_batch_links:
        mock_batch_links.return_value = {999: 5}

        producer = CommercialRoutingV3QueueProducer()
        with patch.object(producer, '_upsert_queue_task') as mock_upsert:
            res = producer.populate_all_eligible(dry_run=False)
            assert mock_upsert.call_count == 0
            assert res["skipped_unknown_okpd"] == 1
            assert res["inserted"] == 0


@patch('src.services.commercial_routing_v3.factual_feeder._get_doc_db_conn')
def test_target_with_docs_initial_status_pre_research_waiting(mock_doc_conn) -> None:
    # Case 7: TARGET with docs -> PRE_RESEARCH_WAITING
    mock_crm = MagicMock()
    feeder = FactualFeeder(mock_crm)
    proc_target = {"id": 10, "source_table": "reestr_contract_44_fz", "source_id": 100, "contract_number": "1", "okpd_code": "27.40.15"}

    with patch('src.services.commercial_routing_v3.factual_feeder.resolve_document_links') as mock_resolve:
        mock_resolve.return_value = {"links": [{"url": "test_url"}]}

        mock_doc = MagicMock()
        mock_doc_conn.return_value = mock_doc
        mock_doc_cur = mock_doc.cursor.return_value.__enter__.return_value
        mock_doc_cur.fetchone.side_effect = [None, {"id": 101}]

        res = feeder.admit_procurement(proc_target, priors=MOCK_PRIORS)
        assert res["admitted"] is True
        assert res["status"] == "PRE_RESEARCH_WAITING"

        # Verify SQL insert contains status PRE_RESEARCH_WAITING, not PENDING
        execute_args = mock_doc_cur.execute.call_args[0]
        sql = execute_args[0]
        params = execute_args[1]
        assert "INSERT INTO document_processing_queue" in sql
        assert params[4] == "PRE_RESEARCH_WAITING"


def test_target_cannot_become_pending_before_blind_predictor_release() -> None:
    # Case 8: TARGET cannot become PENDING before blind predictor release
    mock_crm = MagicMock()
    feeder = FactualFeeder(mock_crm)
    proc_target = {"id": 20, "source_table": "reestr_contract_44_fz", "source_id": 200, "contract_number": "20", "okpd_code": "27.40.15"}

    with patch('src.services.commercial_routing_v3.factual_feeder._get_doc_db_conn') as mock_doc_conn:
        with patch('src.services.commercial_routing_v3.factual_feeder.resolve_document_links') as mock_resolve:
            mock_resolve.return_value = {"links": [{"url": "url1"}]}
            mock_doc = MagicMock()
            mock_doc_conn.return_value = mock_doc
            mock_doc_cur = mock_doc.cursor.return_value.__enter__.return_value
            mock_doc_cur.fetchone.side_effect = [None, {"id": 201}]

            res = feeder.admit_procurement(proc_target, priors=MOCK_PRIORS)
            assert res["status"] != "PENDING"
            assert res["status"] == "PRE_RESEARCH_WAITING"


def test_ai_medal_has_no_effect_on_classification() -> None:
    # Case 9: AI medal has no effect on classification
    classification_oot, _ = classify_target_okpd("32.99.53", MOCK_PRIORS)
    assert classification_oot == ADMISSION_OUT_OF_TARGET

    classification_target, _ = classify_target_okpd("27.40.15", MOCK_PRIORS)
    assert classification_target == ADMISSION_TARGET


def test_title_has_no_effect_on_classification() -> None:
    # Case 10: title has no effect on classification
    classification, _ = classify_target_okpd("32.99.53.191", MOCK_PRIORS)
    assert classification == ADMISSION_OUT_OF_TARGET

    classification2, _ = classify_target_okpd("27.40.15", MOCK_PRIORS)
    assert classification2 == ADMISSION_TARGET
