"""Targeted projection-writer safeguards ported from S13."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.services.commercial_routing_v3 import projection_writer as pw
from src.services.commercial_routing_v3.projection import (
    SourceStage,
    stage_from_source_table,
)


class FakeCrm:
    def __init__(self, columns: set[str] | None = None) -> None:
        self.columns = columns
        self.updates: list[tuple[str, dict]] = []

    def execute_query(self, sql, params=None):
        assert "information_schema.columns" in sql
        return [{"column_name": name} for name in self.columns or set()]

    def execute_update(self, sql, params):
        self.updates.append((sql, params))


class UndefinedColumnError(Exception):
    diag = SimpleNamespace(sqlstate="42703")


class SchemaFailCrm:
    def execute_update(self, sql, params):
        raise UndefinedColumnError('column "required" does not exist')


def _row(source_table: str, source_id: int, **extra):
    return {
        "source_table": source_table,
        "source_id": source_id,
        "contract_number": "CN-1",
        "auction_name": "Procurement",
        "end_date": "2099-12-31",
        **extra,
    }


def test_terminal_lifecycle_has_precedence() -> None:
    terminal_table = "reestr_contract_44_fz_completed"
    assert stage_from_source_table(terminal_table) is SourceStage.TERMINAL
    assert pw._crm_stage_for(terminal_table, None) == (
        "commission",
        "terminal_no_result",
    )

    awarded = _row(
        "reestr_contract_44_fz_awarded",
        10,
        start_date="2026-01-01",
        initial_price=100,
    )
    terminal = _row(terminal_table, 20)
    out = pw._dedupe_by_lifecycle([awarded, terminal])
    assert len(out) == 1
    assert out[0]["source_table"] == terminal_table


def test_same_logical_input_is_deterministic() -> None:
    low_id = _row("reestr_contract_44_fz", 7)
    high_id = _row("reestr_contract_44_fz", 8)
    first = pw._dedupe_by_lifecycle([low_id, high_id])
    second = pw._dedupe_by_lifecycle([high_id, low_id])
    assert first == second == [high_id]


def test_strong_state_is_not_downgraded_by_weaker_source_row() -> None:
    crm = FakeCrm(columns={"id", "crm_stage", "source_table", "deadline_trust"})
    action = pw._upsert_one(
        crm,
        _row("reestr_contract_44_fz", 1),
        existing={
            "id": 5,
            "crm_stage": "razygranye",
            "source_table": "reestr_contract_44_fz_awarded",
        },
        dry_run=False,
    )
    assert action == "skipped_lifecycle_downgrade"
    assert crm.updates == []


def test_optional_absent_column_does_not_break_supported_write() -> None:
    crm = FakeCrm(columns={"id", "crm_stage", "source_table"})
    action = pw._upsert_one(
        crm,
        _row("reestr_contract_44_fz", 11),
        existing=None,
        dry_run=False,
    )
    assert action == "insert"
    assert len(crm.updates) == 1
    assert "deadline_trust" not in crm.updates[0][0]
    assert "final_contract_price,\n                )" not in crm.updates[0][0]


def test_present_optional_column_keeps_insert_sql_valid() -> None:
    crm = FakeCrm(
        columns={"id", "crm_stage", "source_table", "deadline_trust"}
    )
    action = pw._upsert_one(
        crm,
        _row("reestr_contract_44_fz", 11),
        existing=None,
        dry_run=False,
    )
    assert action == "insert"
    sql = crm.updates[0][0]
    assert "final_contract_price,\n                    deadline_trust" in sql
    assert ",," not in sql


def test_schema_error_is_not_hidden_by_broad_exception() -> None:
    with pytest.raises(UndefinedColumnError):
        pw._upsert_one(
            SchemaFailCrm(),
            _row("reestr_contract_44_fz", 12),
            existing=None,
            dry_run=False,
        )
