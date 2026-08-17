from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
S7 = REPO / "eis_ingestion" / "s7_forward"
S13 = REPO / "eis_ingestion" / "s13_backfill"
TAGS = json.loads(
    (S7 / "required_tags" / "required_tags_44_fz_recouped.json").read_text(encoding="utf-8")
)

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export>
  <contract>
    <order><notificationNumber>1111111111111111111</notificationNumber></order>
    <executionPeriod>
      <startDate>2026-01-10</startDate>
      <endDate>2026-11-30</endDate>
    </executionPeriod>
    <priceInfo><price>1500.50</price></priceInfo>
    <contractSubject>Ремонт кровли школы</contractSubject>
    <OKPD2><code>41.20.10</code></OKPD2>
    <legalEntityRF>
      <EGRULInfo>
        <shortName>ООО Тест</shortName>
        <fullName>ООО Тест Полное</fullName>
        <INN>7701234567</INN>
        <KPP>770101001</KPP>
      </EGRULInfo>
    </legalEntityRF>
    <printForm><url>http://example.test/doc</url></printForm>
  </contract>
</export>
"""


def _s7():
    sys.path.insert(0, str(S7))


def _record(**kwargs):
    _s7()
    from parsing_xml.rgk_record import RGKRecord

    payload = dict(
        file_name="a.xml",
        file_path="/tmp/a.xml",
        contract_number="111",
        auction_name="Ремонт кровли школы",
        delivery_start_date="2026-01-10",
        delivery_end_date="2026-11-30",
        final_price="1500.50",
        okpd_codes=["41.20.10"],
        okpd_code="41.20.10",
        contractor_inn="7701234567",
        version_key="k1",
        raw_file="a.xml",
    )
    payload.update(kwargs)
    return RGKRecord(**payload)


def _awarded_row(**kwargs):
    row = {
        "table_name": "reestr_contract_44_fz_awarded",
        "record_id": 10,
        "contract_number": "111",
        "final_price": "1500.50",
        "contractor_id": 7,
        "delivery_start_date": "2026-01-10",
        "delivery_end_date": "2026-11-30",
        "auction_name": "Ремонт кровли школы",
        "okpd_id": 42,
    }
    row.update(kwargs)
    return row


def test_dirty_check_null_safe_and_skip_identical():
    _s7()
    from database_work.rgk_dirty import changed_fields, row_is_dirty

    existing = _awarded_row()
    incoming = {
        "final_price": "1500.50",
        "contractor_id": 7,
        "delivery_start_date": "2026-01-10",
        "delivery_end_date": "2026-11-30",
        "auction_name": "Ремонт кровли школы",
        "okpd_id": 42,
    }
    assert row_is_dirty(existing, incoming) is False
    incoming["final_price"] = "1600"
    assert changed_fields(existing, incoming) == ["final_price"]
    incoming["final_price"] = None
    incoming["contractor_id"] = 8
    assert changed_fields(existing, incoming) == ["contractor_id"]
    incoming["contractor_id"] = 7
    incoming["delivery_end_date"] = None
    assert row_is_dirty(existing, incoming) is False
    existing_null = _awarded_row(final_price=None)
    assert row_is_dirty(existing_null, {"final_price": "1"}) is True


def test_lookup_priority_main_beats_awarded():
    _s7()
    from database_work.rgk_batch_sql import merge_registry_priority

    rows = {
        "reestr_contract_44_fz": [(1, "111", 10, 2, None, None, "A", 3)],
        "reestr_contract_44_fz_awarded": [(9, "111", 99, 2, None, None, "B", 3)],
    }
    found = merge_registry_priority(rows)
    assert found["111"]["table_name"] == "reestr_contract_44_fz"
    assert found["111"]["record_id"] == 1


def test_parse_rgk_once(tmp_path):
    _s7()
    from parsing_xml.rgk_record import parse_rgk_file

    path = tmp_path / "contract_1111111111111111111_1.xml"
    path.write_text(SAMPLE_XML, encoding="utf-8")
    record, passes = parse_rgk_file(str(path), TAGS)
    assert passes == 1
    assert record is not None
    assert record.contract_number == "1111111111111111111"
    assert record.final_price == "1500.50"
    assert record.delivery_start_date == "2026-01-10"
    assert record.delivery_end_date == "2026-11-30"
    assert record.auction_name == "Ремонт кровли школы"
    assert record.okpd_codes == ["41.20.10"]
    assert record.contractor_inn == "7701234567"
    assert record.document_links
    record2, passes2 = parse_rgk_file(str(path), TAGS)
    assert passes2 == 1
    assert record2.version_key == record.version_key


def test_sql_builders_are_bulk_not_per_row():
    _s7()
    from database_work.rgk_batch_sql import (
        UPDATE_VALUE_TEMPLATE,
        build_batch_update_sql,
        build_filename_lookup_sql,
        build_okpd_lookup_sql,
        build_registry_lookup_sql,
        statements_for_batch,
    )

    lookup = build_registry_lookup_sql("reestr_contract_44_fz_awarded")
    assert "ANY(%s)" in lookup
    assert "UNION" not in lookup
    assert "LIMIT 1" not in lookup
    assert "ANY(%s)" in build_okpd_lookup_sql()
    assert "ANY(%s)" in build_filename_lookup_sql()
    update_sql = build_batch_update_sql("reestr_contract_44_fz_awarded")
    assert "FROM (VALUES %s)" in update_sql
    assert "COALESCE" in update_sql
    assert "%s::int" in UPDATE_VALUE_TEMPLATE
    stats = statements_for_batch(
        lookup_tables=5,
        update_tables=2,
        promote_sources=1,
        inserts=2,
        unresolved_writes=1,
        contractor_inserts=3,
        has_filenames=True,
        has_links=True,
    )
    per_1000 = {key: value * 2 for key, value in stats.items()}
    assert per_1000["selects"] <= 50
    assert per_1000["commits"] <= 5


def test_correctness_parity_cases():
    _s7()
    from database_work.rgk_plan import plan_44_batch

    okpd = {"41.20.10": 42}
    contractors = {"7701234567": 7}

    identical = _record(contractor_id=7, okpd_id=42)
    plan = plan_44_batch(
        [identical],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": _awarded_row()},
        unresolved_map={},
        version_cache={},
    )
    assert plan.updates == []
    assert plan.metrics["unchanged"] == 1
    assert plan.metrics["updates_skipped"] == 1

    changed_price = _record(final_price="2000")
    plan = plan_44_batch(
        [changed_price],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": _awarded_row()},
        unresolved_map={},
        version_cache={},
    )
    assert len(plan.updates) == 1
    assert plan.updates[0].fields["final_price"] == "2000"
    assert plan.updates[0].table_name.endswith("_awarded")

    changed_contractor = _record(contractor_inn="7709999999")
    plan = plan_44_batch(
        [changed_contractor],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map={"7709999999": 99},
        registry_map={"111": _awarded_row()},
        unresolved_map={},
        version_cache={},
    )
    assert plan.updates[0].fields["contractor_id"] == 99

    dates = _record(delivery_start_date="2026-02-01", delivery_end_date="2027-01-01")
    plan = plan_44_batch(
        [dates],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": _awarded_row()},
        unresolved_map={},
        version_cache={},
    )
    assert "delivery_start_date" in plan.updates[0].fields
    assert "delivery_end_date" in plan.updates[0].fields

    main_row = _awarded_row(table_name="reestr_contract_44_fz", record_id=3)
    main_row["contractor_id"] = None
    promote_rec = _record()
    plan = plan_44_batch(
        [promote_rec],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": main_row},
        unresolved_map={},
        version_cache={},
    )
    assert plan.promotes and plan.promotes[0].promote is True
    assert plan.promotes[0].table_name == "reestr_contract_44_fz"

    unclear_row = _awarded_row(table_name="reestr_contract_44_fz_unclear", record_id=4)
    unclear_row["contractor_id"] = None
    plan = plan_44_batch(
        [_record()],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": unclear_row},
        unresolved_map={},
        version_cache={},
    )
    assert plan.promotes[0].table_name.endswith("_unclear")

    plan = plan_44_batch(
        [_record(contract_number="new1", file_name="n.xml")],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={},
        unresolved_map={},
        version_cache={},
    )
    assert len(plan.inserts) == 1
    assert plan.inserts[0].fields["okpd_id"] == 42
    assert not plan.inserts[0].fields["auction_name"].startswith("Контракт ")

    plan = plan_44_batch(
        [_record(okpd_codes=["99.00.00"], okpd_code="99.00.00", contract_number="miss")],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={},
        unresolved_map={},
        version_cache={},
    )
    assert plan.inserts == []
    assert plan.unresolved[0].reason == "MISSING_OKPD_ID"

    plan = plan_44_batch(
        [_record(okpd_codes=["99.00.00"], okpd_code="99.00.00", contract_number="miss")],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={},
        unresolved_map={"miss": {"reason": "MISSING_OKPD_ID", "okpd_codes": ["99.00.00"], "contract_subject": "Ремонт кровли школы"}},
        version_cache={},
    )
    assert plan.unresolved == []
    assert plan.metrics["unresolved_unchanged"] == 1

    plan = plan_44_batch(
        [_record(file_name="dup.xml")],
        known_filenames={"dup.xml"},
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": _awarded_row()},
        unresolved_map={},
        version_cache={},
    )
    assert plan.metrics["duplicates"] == 1
    assert plan.updates == []
    assert "dup.xml" not in plan.filenames

    v1 = _record(file_name="v1.xml", final_price="1500.50", version_key="v1")
    v2 = _record(file_name="v2.xml", final_price="3000", version_key="v2")
    plan = plan_44_batch(
        [v1, v2],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": _awarded_row()},
        unresolved_map={},
        version_cache={},
    )
    assert len(plan.updates) == 1
    assert plan.updates[0].fields["final_price"] == "3000"
    assert plan.filenames == ["v1.xml", "v2.xml"]

    plan = plan_44_batch(
        [_record(final_price="1500.50")],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": _awarded_row(final_price=None)},
        unresolved_map={},
        version_cache={},
    )
    assert plan.updates[0].fields["final_price"] == "1500.50"


def test_canonical_source_order_beats_filename_order():
    """Later EIS publish must win even if that XML is last in glob/filename order."""
    _s7()
    from database_work.rgk_plan import plan_44_batch

    okpd = {"41.20.10": 42}
    contractors = {"7701234567": 7}
    older = _record(
        file_name="contract_1690501088826000247_0_019FFA6CB777771588BAFFC729E099B3.xml",
        final_price="25523736.57",
        source_version="0",
        source_publish="2026-08-13T12:20:54.152+03:00",
        version_key="older",
    )
    newer = _record(
        file_name="contract_1540810634826001084_0_019FFA79FCD27203823F582E5367B163.xml",
        final_price="25706116.47",
        source_version="0",
        source_publish="2026-08-13T16:35:24.177+07:00",
        version_key="newer",
    )
    plan = plan_44_batch(
        [older, newer],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": _awarded_row(final_price="1.00")},
        unresolved_map={},
        version_cache={},
    )
    assert plan.updates[0].fields["final_price"] == "25706116.47"

    plan = plan_44_batch(
        [newer, older],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": _awarded_row(final_price="1.00")},
        unresolved_map={},
        version_cache={},
    )
    assert plan.updates[0].fields["final_price"] == "25706116.47"

    earlier_clock = _record(
        file_name="contract_1_0_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.xml",
        final_price="10.00",
        source_version="0",
        source_publish="2026-08-13T18:00:00+07:00",
        version_key="tz-early",
    )
    later_clock = _record(
        file_name="contract_2_0_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB.xml",
        final_price="20.00",
        source_version="0",
        source_publish="2026-08-13T15:00:00+03:00",
        version_key="tz-late",
    )
    plan = plan_44_batch(
        [later_clock, earlier_clock],
        known_filenames=set(),
        okpd_map=okpd,
        contractor_map=contractors,
        registry_map={"111": _awarded_row(final_price="1.00")},
        unresolved_map={},
        version_cache={},
    )
    assert plan.updates[0].fields["final_price"] == "20.00"


def test_links_only_for_main_table_ids():
    _s7()
    from database_work.registry_tables import tables_for_fz
    from database_work.rgk_plan import plan_44_batch

    rec = _record(document_links=[{"file_name": "doc", "document_links": "http://x"}])
    plan = plan_44_batch(
        [rec],
        known_filenames=set(),
        okpd_map={"41.20.10": 42},
        contractor_map={"7701234567": 7},
        registry_map={"111": _awarded_row(final_price="9")},
        unresolved_map={},
        version_cache={},
    )
    main = tables_for_fz("44").main
    main_ids = {
        int(write.record_id)
        for write in plan.inserts + plan.updates
        if write.table_name == main and write.record_id is not None
    }
    assert plan.updates
    assert plan.updates[0].table_name.endswith("_awarded")
    assert main_ids == set()
    assert all(item["contract_id"] not in main_ids for item in plan.links())


def test_replay_statement_budget_5000():
    _s7()
    from database_work.rgk_batch_sql import statements_for_batch
    from database_work.rgk_plan import plan_44_batch

    records = []
    registry = {}
    for index in range(5000):
        number = str(index)
        records.append(
            _record(
                file_name=f"{index}.xml",
                contract_number=number,
                version_key=f"k{index}",
                final_price="1500.50" if index % 10 else "9999",
            )
        )
        registry[number] = _awarded_row(contract_number=number, record_id=index + 1)
    started = time.perf_counter()
    plan = plan_44_batch(
        records,
        known_filenames=set(),
        okpd_map={"41.20.10": 42},
        contractor_map={"7701234567": 7},
        registry_map=registry,
        unresolved_map={},
        version_cache={},
    )
    new_seconds = time.perf_counter() - started
    assert plan.metrics["found"] == 5000
    assert plan.metrics["unchanged"] == 4500
    assert plan.metrics["changed"] == 500
    assert plan.metrics["updates_skipped"] == 4500
    assert len(plan.updates) == 500
    stats = statements_for_batch(
        lookup_tables=5,
        update_tables=1,
        promote_sources=0,
        inserts=0,
        unresolved_writes=0,
        contractor_inserts=0,
        has_filenames=True,
        has_links=False,
    )
    # 10 batches of 500 for 5000 XML; scale per-batch bound.
    selects_per_1000 = stats["selects"] * 2
    commits_per_1000 = stats["commits"] * 2
    assert selects_per_1000 <= 50
    assert commits_per_1000 <= 5
    old_selects_per_1000 = 2500
    old_commits_per_1000 = 2000
    assert selects_per_1000 * 10 <= old_selects_per_1000
    assert commits_per_1000 * 10 <= old_commits_per_1000
    old_seconds = 5000 / 3.6
    assert new_seconds * 10 < old_seconds


def test_batch_size_clamp(monkeypatch):
    _s7()
    from parsing_xml.rgk_batch import rgk_batch_size

    monkeypatch.setenv("TENDERMONITOR_RGK_BATCH_SIZE", "500")
    assert rgk_batch_size() == 500
    monkeypatch.setenv("TENDERMONITOR_RGK_BATCH_SIZE", "10")
    assert rgk_batch_size() == 100
    monkeypatch.setenv("TENDERMONITOR_RGK_BATCH_SIZE", "99999")
    assert rgk_batch_size() == 2000


def test_44_folder_uses_batch_path():
    text = (S7 / "parsing_xml" / "okpd_parser.py").read_text(encoding="utf-8")
    assert "process_44_rgk_folder" in text
    assert "S13" not in text


def test_s13_backward_untouched():
    s7 = (S7 / "database_work" / "contract_registry_locator.py").read_bytes()
    s13 = (S13 / "database_work" / "contract_registry_locator.py").read_bytes()
    assert s7 != s13
    recouped = json.loads(
        (S7 / "required_tags" / "required_tags_223_fz_recouped.json").read_text(encoding="utf-8")
    )
    contract = recouped["reestr_contract"]
    assert contract["delivery_start_date"] == "contractData/startExecutionDate"
    assert contract["delivery_end_date"] == "contractData/endExecutionDate"
    assert contract["final_price"] == "contractData/price"
    assert "unitPrice" not in json.dumps(recouped)
    assert "documentationDelivery" not in json.dumps(recouped)
