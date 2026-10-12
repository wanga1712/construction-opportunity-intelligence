"""Tests for the CRM-side 615-ПП ↔ УК linkage store.

Ключевой инвариант: отсутствие данных (нет прав, нет связи, нет миграции)
никогда не показывается как «0 торгов». Ноль — только там, где он посчитан.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.services.waterproofing_615 import (
    TenderSourceUnavailable,
    build_index,
    load_615_slice,
    program_years,
    year_overview,
)
from src.services.waterproofing_615_refresh import (
    ADDRESS_INSERT,
    LINK_INSERT,
    PROGRAM_INSERT,
    build_payload,
    run_refresh,
    write_failure,
    write_payload,
)
from src.services.waterproofing_615_store import (
    STALE_AFTER_HOURS,
    STATUS_FAILED,
    STATUS_FRESH,
    STATUS_NEVER_RUN,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    STORE_TABLES,
    StoreNotReady,
    board_615_line,
    board_query,
    ensure_store_ready,
    freshness,
    read_board,
    read_program_year,
    read_uk_summary,
)
from src.services.waterproofing_crm import board_kpis, build_card

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


class FakeCrm:
    """Minimal CRM handle: answers schema probes and the store queries."""

    def __init__(self, *, tables=None, board_rows=(), matches=(), program=(), state=None):
        self.tables = set(tables if tables is not None else STORE_TABLES)
        self.board_rows = list(board_rows)
        self.matches = list(matches)
        self.program = list(program)
        self.state = dict(state or {})
        self.queries: list[str] = []

    @staticmethod
    def _name(params):
        text = str((params or {}).get("fqn") or "")
        return text.split(".")[-1]

    def execute_query(self, sql, params=None, fetch_results=True, timeout=None):
        self.queries.append(sql)
        if "to_regclass" in sql:
            return [{"ok": self._name(params) in self.tables}]
        if "MIN(address_text) AS address_text" in sql:
            return list(self.matches)
        if "crm_waterproofing_615_program_year" in sql:
            return list(self.program)
        if "crm_waterproofing_615_sync_state" in sql:
            return [dict(self.state)]
        if "AS approximate_matches" in sql:
            return list(self.board_rows)
        raise AssertionError(f"unexpected SQL: {sql[:80]}")

    def execute_update(self, sql, params=None, timeout=None):
        raise AssertionError("store read path must not write")


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append(("execute", sql, params))

    def executemany(self, sql, params_list):
        self.log.append(("executemany", sql, list(params_list)))


class FakeConn:
    def __init__(self):
        self.log: list[tuple] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self.log)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeDb:
    """CRM handle stub: schema probe answers "present", connection is the fake."""

    def __init__(self, conn):
        self._conn = conn

    def get_connection(self):
        return self._conn

    def execute_query(self, sql, params=None, fetch_results=True, timeout=None):
        if "to_regclass" in sql:
            return [{"ok": True}]
        raise AssertionError(f"unexpected SQL: {sql[:80]}")


class BrokenTender:
    def __init__(self, *, offline=False, message="permission denied for table reestr_contract_615_pp"):
        self.offline = offline
        self.message = message

    def is_offline_mode(self):
        return self.offline

    def is_connected(self):
        return not self.offline

    def connect(self):
        return None

    def get_connection(self):
        raise RuntimeError(self.message)


@pytest.fixture
def tender_rows():
    return [
        {"id": 1, "contract_number": "A-1", "start_date": "2026-03-01", "initial_price": 1e6,
         "final_price": 700e6, "is_waterproofing": True, "delivery_address": "Селигерская ул. 16"},
        {"id": 2, "contract_number": "A-2", "start_date": "2025-04-05", "initial_price": 2e6,
         "final_price": 500e6, "is_waterproofing": False, "delivery_address": "Хабаровская ул. 4"},
        {"id": 3, "contract_number": "A-3", "start_date": "2024-06-07", "initial_price": 3e6,
         "final_price": 300e6, "is_waterproofing": False, "delivery_address": "Хабаровская ул. 4"},
        {"id": 4, "contract_number": "A-4", "start_date": "2026-08-09", "initial_price": 4e6,
         "final_price": 100e6, "is_waterproofing": False, "delivery_address": "Москва"},
    ]


def test_strict_reader_raises_instead_of_returning_empty():
    with pytest.raises(TenderSourceUnavailable) as error:
        load_615_slice(BrokenTender(), strict=True)
    assert "permission denied" in error.value.reason


def test_strict_reader_reports_offline_source():
    with pytest.raises(TenderSourceUnavailable):
        load_615_slice(BrokenTender(offline=True), strict=True)


def test_non_strict_reader_keeps_legacy_empty_result():
    slice_data = load_615_slice(BrokenTender())
    assert slice_data["rows"] == []
    assert slice_data["overview"]["tenders"] == 0


def test_strict_reader_reports_missing_handle():
    with pytest.raises(TenderSourceUnavailable):
        load_615_slice(None, strict=True)


def test_program_years_covers_every_year_with_contracts(tender_rows):
    years = {row["year"] for row in program_years(tender_rows)}
    assert years == {"2024", "2025", "2026"}


def test_build_payload_links_only_matched_houses(tender_rows):
    index = build_index(tender_rows)
    slice_data = {"index": index, "rows": tender_rows, "year": 2026,
                  "overview": year_overview(tender_rows, 2026)}
    payload = build_payload(slice_data, {"UK1": ["Селигерская ул. 16", "Правды ул. 9"]})
    assert payload["uk_with_tenders"] == 1
    assert len(payload["addresses"]) == 2
    assert sorted(row[3] for row in payload["addresses"]) == ["exact", "none"]
    assert [row[3] for row in payload["links"]] == ["1"]
    assert payload["source_contracts"] == len(tender_rows)


def test_build_payload_deduplicates_same_house_across_objects(tender_rows):
    index = build_index(tender_rows)
    slice_data = {"index": index, "rows": tender_rows}
    payload = build_payload(slice_data, {"UK1": ["Хабаровская ул. 4", "Хабаровская улица дом 4"]})
    assert len(payload["addresses"]) == 1
    assert len(payload["links"]) == 2


def test_build_payload_marks_fuzzy_match(tender_rows):
    index = build_index(tender_rows)
    slice_data = {"index": index, "rows": tender_rows}
    payload = build_payload(slice_data, {"UK1": ["Большая Хабаровская 4"]})
    row = payload["addresses"][0]
    assert row[3] == "fuzzy" and 0.5 <= row[4] < 1.0


def test_payload_is_idempotent(tender_rows):
    index = build_index(tender_rows)
    slice_data = {"index": index, "rows": tender_rows}
    grouped = {"UK1": ["Селигерская ул. 16"], "UK2": ["Москва"]}
    assert build_payload(slice_data, grouped) == build_payload(slice_data, grouped)


def test_write_payload_replaces_store_in_one_transaction(tender_rows):
    payload = build_payload({"index": build_index(tender_rows), "rows": tender_rows},
                            {"UK1": ["Селигерская ул. 16"]})
    conn = FakeConn()
    counts = write_payload(conn, payload, history_from=2019, duration_ms=7, attempt=NOW)
    kinds = [entry[0] for entry in conn.log]
    assert kinds[0:3] == ["execute", "execute", "execute"]
    deletes = [entry[1] for entry in conn.log if entry[0] == "execute"]
    assert all("DELETE FROM crm_waterproofing_615" in sql for sql in deletes[:3])
    inserts = [entry for entry in conn.log if entry[0] == "executemany"]
    assert {entry[1] for entry in inserts} == {ADDRESS_INSERT, LINK_INSERT, PROGRAM_INSERT}
    assert conn.commits == 1 and conn.rollbacks == 0
    assert counts["links"] == 1 and counts["addresses"] == 1
    assert counts["program_years"] == 3


def test_write_failure_keeps_last_success_by_not_touching_it():
    conn = FakeConn()
    write_failure(conn, TenderSourceUnavailable("нет прав"), duration_ms=3, attempt=NOW)
    sql = conn.log[0][1]
    assert "ON CONFLICT" in sql and "last_success_at" not in sql.split("DO UPDATE")[1]
    assert conn.commits == 1


def test_run_refresh_reports_failure_without_writing_zeros():
    conn = FakeConn()
    with pytest.raises(TenderSourceUnavailable):
        run_refresh(tender_db=BrokenTender(), crm_db=FakeDb(conn), parking_db=_NoAddresses(),
                    now=NOW)
    executed = [entry for entry in conn.log if entry[0] == "execute"]
    assert any("'FAILED'" in entry[1] for entry in executed)
    # Провал не пишет нули в таблицы-накопители: только статус обновления.
    assert [entry for entry in conn.log if entry[0] == "executemany"] == []
    assert conn.commits == 1


class _NoAddresses:
    def query_all(self, sql, params=None):
        return []


def test_ensure_store_ready_accepts_existing_tables():
    ensure_store_ready(FakeCrm())


def test_ensure_store_ready_is_fail_closed_without_migration():
    with pytest.raises(StoreNotReady) as error:
        ensure_store_ready(FakeCrm(tables=set()))
    assert set(error.value.missing) == {f"public.{table}" for table in STORE_TABLES}


def test_ensure_store_ready_without_db_handle():
    with pytest.raises(Exception) as error:
        ensure_store_ready(None)
    assert "не создано" in str(error.value)


def _board_row(**overrides):
    row = {
        "uk_key": "UK1", "history_tenders": 3, "history_amount": 1500e6,
        "history_waterproofing_tenders": 1, "years": [2024, 2025, 2026],
        "history_last_date": "2026-03-01", "year_tenders": 1, "year_amount": 700e6,
        "year_waterproofing_tenders": 1, "year_waterproofing_amount": 700e6,
        "year_last_date": "2026-03-01", "matched_addresses": 1, "approximate_matches": 0,
        "checked_addresses": 2,
    }
    row.update(overrides)
    return row


def _state(**overrides):
    state = {"source": "TENDER_MONITOR_615", "status": "SUCCESS",
             "last_attempt_at": NOW, "last_success_at": NOW,
             "history_from_year": 2019, "link_rows": 1, "checked_addresses": 2,
             "source_contracts": 3883, "uk_with_tenders": 1}
    state.update(overrides)
    return state


def test_read_board_maps_rows_to_card_summary_shape():
    db = FakeCrm(board_rows=[_board_row()], state=_state(),
                 program=[{"year": 2026, "tenders": 1082, "amount": 190284328509.68,
                           "waterproofing_tenders": 3, "waterproofing_amount": 700149592.85}])
    snapshot = read_board(db, year=2026, now=NOW)
    assert snapshot["status"] == STATUS_FRESH
    summary = snapshot["uk"]["UK1"]
    assert summary["history_from"] == 2019
    assert summary["checked_addresses"] == 2
    card = build_card({"uk_name": "УК", "object_count": 1}, tenders_615=summary)
    assert card["tenders_615_count"] == 3
    assert card["tenders_615_year_count"] == 1
    assert card["tenders_615_year_amount"] == 700e6


def test_read_board_without_store_is_unavailable_not_zero():
    snapshot = read_board(FakeCrm(tables=set()), year=2026, now=NOW)
    assert snapshot["status"] == STATUS_UNAVAILABLE
    assert snapshot["uk"] == {}
    line = board_615_line(snapshot, {"tenders_615_uk": 0, "tenders_615": 0,
                                     "tenders_615_year": 0})
    assert line["level"] == "warning"
    assert "не создано" in line["text"]
    assert "0 торгов" not in line["text"]


def test_read_board_without_db_handle_is_unavailable():
    snapshot = read_board(None, year=2026, now=NOW)
    assert snapshot["status"] == STATUS_UNAVAILABLE and not snapshot["available"]


def test_read_board_missing_year_does_not_invent_numbers():
    db = FakeCrm(board_rows=[], state=_state(), program=[])
    snapshot = read_board(db, year=2027, now=NOW)
    assert snapshot["overview"] == {}
    line = board_615_line(snapshot, {"tenders_615_uk": 0, "tenders_615": 0,
                                     "tenders_615_year": 0})
    assert "за 2027 данных" in line["text"]


def test_freshness_flags_stale_data():
    old = NOW - timedelta(hours=STALE_AFTER_HOURS + 1)
    status, message = freshness(_state(last_success_at=old), NOW)
    assert status == STATUS_STALE and "устарели" in message


def test_freshness_reports_failed_run_with_last_data_date():
    status, message = freshness(_state(status="FAILED", safe_error_class="OperationalError"),
                                NOW)
    assert status == STATUS_FAILED
    assert "OperationalError" in message and "2026-09-28" in message


def test_freshness_reports_never_run():
    status, message = freshness({"status": "NEVER_RUN", "last_success_at": None}, NOW)
    assert status == STATUS_NEVER_RUN and "не обновлялась" in message


def test_board_615_line_fresh_is_caption_and_shows_refresh_date():
    db = FakeCrm(board_rows=[_board_row()], state=_state(),
                 program=[{"year": 2026, "tenders": 1082, "amount": 190284328509.68,
                           "waterproofing_tenders": 3,
                           "waterproofing_amount": 700149592.85}])
    snapshot = read_board(db, year=2026, now=NOW)
    line = board_615_line(snapshot, board_kpis([
        build_card({"uk_name": "УК"}, tenders_615=snapshot["uk"]["UK1"])
    ]))
    assert line["level"] == "caption"
    assert "1082 торгов" in line["text"] and "Обновлено 2026-09-28" in line["text"]


def test_board_kpis_year_amount_uses_current_year_only():
    card = build_card({"uk_name": "УК"}, tenders_615={
        "year": "2026", "tenders": 1, "amount": 20e6,
        "history_tenders": 3, "history_amount": 100e6,
    })
    kpis = board_kpis([card])
    assert kpis["tenders_615_amount"] == 100e6
    assert kpis["tenders_615_year_amount"] == 20e6
    assert kpis["tenders_615_year_amount_label"] != kpis["tenders_615_amount_label"]


def test_read_uk_summary_needs_store_and_returns_matches():
    db = FakeCrm(board_rows=[_board_row()], state=_state(), program=[],
                 matches=[{"address_key": "селигерская 16", "address_text": "Селигерская ул. 16",
                           "tenders": 1, "amount": 700e6, "last_date": NOW.date(),
                           "years": [2026], "match_score": 1.0, "year_tenders": 1,
                           "year_amount": 700e6}])
    summary = read_uk_summary(db, "UK1", year=2026)
    assert summary["matches"][0]["confidence"] == "точное"
    assert summary["matches"][0]["tenders"] == 1
    assert read_uk_summary(FakeCrm(tables=set()), "UK1", year=2026) == {}
    assert read_uk_summary(db, "", year=2026) == {}


def test_board_query_single_uk_filters_by_key():
    assert "%(uk_key)s" in board_query(2026, uk_key="UK1")
    assert "%(uk_key)s" not in board_query(2026)


def test_read_program_year_returns_empty_when_year_absent():
    assert read_program_year(FakeCrm(program=[]), 2027) == {}
