from unittest.mock import MagicMock, patch
import pytest
from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer
from src.services.commercial_routing_v3.factual_feeder import FactualFeeder

@patch('psycopg2.connect')
def test_populate_all_eligible_okpd_filtering(mock_connect) -> None:
    mock_crm = MagicMock()
    mock_doc = MagicMock()
    
    mock_connect.side_effect = [mock_crm, mock_doc]
    
    mock_crm_cur = mock_crm.cursor.return_value.__enter__.return_value
    priors_rows = [
        {"commercial_category_code": "lighting", "okpd_pattern": "27.40", "match_type": "PREFIX"},
    ]
    procurements_rows = [
        {"id": 1, "source_table": "reestr_contract_44_fz", "source_id": 100, "contract_number": "1", "okpd_code": "27.40.15", "crm_stage": "open"},
        {"id": 2, "source_table": "reestr_contract_44_fz", "source_id": 101, "contract_number": "2", "okpd_code": "32.99", "crm_stage": "open"},
    ]
    
    mock_crm_cur.fetchall.side_effect = [priors_rows, procurements_rows, []]

    mock_doc_cur = mock_doc.cursor.return_value.__enter__.return_value
    mock_doc_cur.fetchone.side_effect = [None, {"id": 10}, None, {"id": 11}]

    with patch('src.services.commercial_routing_v3.document_links.batch_count_document_links') as mock_batch_links:
        mock_batch_links.return_value = {1: 5, 2: 3}
        
        producer = CommercialRoutingV3QueueProducer()
        res = producer.populate_all_eligible(batch_size=500, max_total=0, dry_run=False)

    assert res["inserted"] == 2
    assert res["target_waiting_inserted"] == 1
    assert res["out_of_target_failed_inserted"] == 1

@patch('src.services.commercial_routing_v3.factual_feeder._get_doc_db_conn')
def test_factual_feeder_okpd_filtering(mock_doc_conn) -> None:
    mock_crm = MagicMock()
    feeder = FactualFeeder(mock_crm)

    priors_rows = [
        {"commercial_category_code": "lighting", "okpd_pattern": "27.40", "match_type": "PREFIX"},
    ]
    mock_crm.execute_query.return_value = priors_rows

    proc_target = {"id": 10, "source_table": "reestr_contract_44_fz", "source_id": 100, "contract_number": "1", "okpd_code": "27.40.15"}
    proc_oot = {"id": 11, "source_table": "reestr_contract_44_fz", "source_id": 101, "contract_number": "2", "okpd_code": "32.99"}

    with patch('src.services.commercial_routing_v3.factual_feeder.resolve_document_links') as mock_resolve:
        mock_resolve.return_value = {"links": [{"url": "test_url"}]}
        
        mock_doc = MagicMock()
        mock_doc_conn.return_value = mock_doc
        mock_doc_cur = mock_doc.cursor.return_value.__enter__.return_value
        mock_doc_cur.fetchone.return_value = None

        res_target = feeder.admit_procurement(proc_target, priors=priors_rows)
        assert res_target["admitted"] is True
        assert res_target["status"] == "PENDING"

        res_oot = feeder.admit_procurement(proc_oot, priors=priors_rows)
        assert res_oot["admitted"] is False
        assert res_oot["status"] == "FAILED"
        assert res_oot["last_error"] == "OUT_OF_TARGET_OKPD"
