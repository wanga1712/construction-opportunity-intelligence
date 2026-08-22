from src.services.annotation_card_view import (
    compose_annotation_card_view,
    load_document_observations,
)


def _header(**overrides):
    row = {
        "id": 7,
        "auction_name": "Капитальный ремонт школы",
        "contract_number": "0123",
        "source_table": "reestr_contract_44_fz",
        "award_status": "submission_open",
        "crm_stage": "torgi",
        "customer": "Заказчик",
        "delivery_region": "Москва",
        "initial_price": 24_100_000,
        "final_price": None,
        "final_contract_price": None,
        "end_date": "2026-09-01",
        "tender_link": "https://example.test/procurement",
    }
    row.update(overrides)
    return row


def _resolved(*documents):
    return {
        "links": list(documents),
        "raw_document_link_count": len(documents),
        "unique_physical_download_target_count": len(documents),
    }


def _document(source_id, url, name="Техническое задание.pdf"):
    return {
        "source_document_id": source_id,
        "source_document_ids": [source_id],
        "source_row_count": 1,
        "document_url": url,
        "document_name": name,
        "document_type": None,
        "link_source": "links_documentation_44_fz",
        "resolution_method": "contract_number",
        "physical_download_key": url,
    }


def test_open_many_documents_without_observations_are_all_unobserved():
    documents = [_document(i, f"https://example.test/{i}") for i in range(35)]
    view = compose_annotation_card_view(
        header=_header(), resolved=_resolved(*documents), observations=[], history=[]
    )
    assert view["document_count"] == 35
    assert {row["observation_state"] for row in view["documents"]} == {"UNOBSERVED"}
    assert view["facts"]["display_amount"] == 24_100_000
    assert view["facts"]["display_amount_label"] == "НМЦК"
    assert view["facts"]["deadline"] == "2026-09-01"
    assert view["facts"]["procurement_url"]


def test_awarded_uses_final_price_and_strict_factual_contract_url():
    contract = _document(
        90,
        "https://zakupki.gov.ru/epz/contract/printForm/view.html?contractInfoId=1",
        "Информация о контракте",
    )
    view = compose_annotation_card_view(
        header=_header(
            source_table="reestr_contract_44_fz_awarded",
            award_status="awarded",
            crm_stage="razygranye",
            initial_price=6_000_000,
            final_contract_price=5_500_000,
            delivery_end_date="2027-01-10",
        ),
        resolved=_resolved(contract), observations=[], history=[],
    )
    assert view["facts"]["display_amount"] == 5_500_000
    assert view["facts"]["display_amount_label"] == "Цена контракта"
    assert view["facts"]["deadline_label"] == "Исполнение до"
    assert view["facts"]["contract_url"] == contract["document_url"]
    assert "source_document_id=90" in view["facts"]["contract_url_provenance"]


def test_observation_joins_by_source_document_id_before_url():
    documents = [
        _document(10, "https://example.test/a"),
        _document(20, "https://example.test/b"),
    ]
    observation = {
        "id": 1,
        "source_document_id": "20",
        "source_document_url": "https://example.test/a",
        "commercial_evidence_found": True,
        "matched_categories": ["paint"],
    }
    view = compose_annotation_card_view(
        header=_header(), resolved=_resolved(*documents), observations=[observation], history=[]
    )
    assert view["documents"][0]["observation_state"] == "UNOBSERVED"
    assert view["documents"][1]["observation_join_method"] == "source_document_id"
    assert view["documents"][1]["observation_state"] == "OBSERVED_WITH_EVIDENCE"


def test_legacy_exact_url_join_and_orphan_are_separate():
    document = _document(10, "https://example.test/a")
    exact = {"id": 1, "source_document_id": None, "source_document_url": "https://example.test/a"}
    orphan = {"id": 2, "source_document_id": 999, "source_document_url": "https://example.test/missing"}
    view = compose_annotation_card_view(
        header=_header(), resolved=_resolved(document), observations=[exact, orphan], history=[]
    )
    assert view["documents"][0]["observation_join_method"] == "exact_url"
    assert view["documents"][0]["observation_state"] == "OBSERVED_NO_EVIDENCE"
    assert [row["id"] for row in view["orphan_observations"]] == [2]


def test_failures_are_distinct_from_no_evidence():
    documents = [_document(10, "https://example.test/a"), _document(20, "https://example.test/b")]
    observations = [
        {"id": 1, "source_document_id": 10, "download_status": "DOWNLOAD_FAILED"},
        {"id": 2, "source_document_id": 20, "parse_status": "SUCCESS", "commercial_evidence_found": False},
    ]
    view = compose_annotation_card_view(
        header=_header(), resolved=_resolved(*documents), observations=observations, history=[]
    )
    assert [row["observation_state"] for row in view["documents"]] == [
        "DOWNLOAD_FAILED", "OBSERVED_NO_EVIDENCE"
    ]


def test_zero_initial_price_is_not_treated_as_missing():
    view = compose_annotation_card_view(
        header=_header(initial_price=0), resolved=_resolved(), observations=[], history=[]
    )
    assert view["facts"]["display_amount"] == 0
    assert view["facts"]["display_amount_label"] == "НМЦК"


def test_observation_loader_is_read_only_complete_and_unlimited():
    class Db:
        def execute_query(self, sql, params):
            assert params == (7,)
            assert "SELECT" in sql
            assert "source_document_id" in sql
            assert "LIMIT" not in sql
            assert not any(word in sql for word in ("INSERT", "UPDATE", "DELETE"))
            return []

    assert load_document_observations(7, Db()) == []
