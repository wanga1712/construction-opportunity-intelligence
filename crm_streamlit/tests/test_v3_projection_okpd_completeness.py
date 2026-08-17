"""Regression: V3 projection must carry S7 OKPD sub_code into S13."""
from __future__ import annotations

from src.services.commercial_routing_v3 import projection_writer as pw


def test_okpd_select_uses_sub_code_not_main_code() -> None:
    assert "o.sub_code AS okpd_code" in pw._OKPD_SELECT
    assert "main_code" not in pw._OKPD_SELECT
    assert "collection_codes_okpd" in pw._OKPD_JOIN


def test_upsert_payload_includes_okpd(monkeypatch) -> None:
    captured = {}

    class FakeCrm:
        def execute_update(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

    action = pw._upsert_one(
        FakeCrm(),
        {
            "source_table": "reestr_contract_44_fz",
            "source_id": 99,
            "contract_number": "CN-99",
            "auction_name": "Поставка",
            "okpd_code": "27.40.33.190",
            "okpd_name": "Прожекторы",
            "initial_price": 1,
            "end_date": None,
        },
        existing=None,
        dry_run=False,
    )
    assert action == "insert"
    assert "okpd_code" in captured["sql"]
    assert captured["params"]["okpd_code"] == "27.40.33.190"
    assert captured["params"]["okpd_name"] == "Прожекторы"


def test_upsert_update_writes_okpd(monkeypatch) -> None:
    captured = {}

    class FakeCrm:
        def execute_update(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

    action = pw._upsert_one(
        FakeCrm(),
        {
            "source_table": "reestr_contract_223_fz",
            "source_id": 7,
            "contract_number": "CN-7",
            "auction_name": "x",
            "okpd_code": "26.20.11.110",
            "okpd_name": "Ноутбуки",
            "end_date": None,
        },
        existing={"id": 1, "crm_stage": "torgi", "source_table": "reestr_contract_223_fz"},
        dry_run=False,
    )
    assert action == "update"
    assert "okpd_code = %(okpd_code)s" in captured["sql"]
    assert captured["params"]["okpd_code"] == "26.20.11.110"
