"""PHASE 3: physical S7 table is the lifecycle authority; dates are not."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.domain.commercial_opportunity_lifecycle import SourceLifecycleEvent as E  # noqa: E402
from src.services.commercial_routing_v3.source_lifecycle import (  # noqa: E402
    normalize_source_lifecycle_event as norm,
)

FUTURE = "2099-01-01"
PAST = "2000-01-01"


def test_44_main_open_regardless_of_date():
    assert norm(source_table="reestr_contract_44_fz", end_date=PAST) == E.OPEN
    assert norm(source_table="reestr_contract_44_fz", end_date=FUTURE) == E.OPEN
    assert norm(source_table="reestr_contract_44_fz", end_date=None) == E.OPEN


def test_223_main_open_regardless_of_date():
    assert norm(source_table="reestr_contract_223_fz", end_date=PAST) == E.OPEN


def test_commission_waiting_regardless_of_date():
    assert norm(source_table="reestr_contract_44_fz_commission_work", end_date=FUTURE) == E.WAITING_SOURCE_OUTCOME
    assert norm(source_table="reestr_contract_223_fz_commission_work", end_date=PAST) == E.WAITING_SOURCE_OUTCOME


def test_awarded_awarded_regardless_of_date():
    assert norm(source_table="reestr_contract_44_fz_awarded", end_date=PAST) == E.AWARDED
    assert norm(source_table="reestr_contract_223_fz_awarded", end_date=FUTURE) == E.AWARDED


def test_terminal_tables():
    assert norm(source_table="reestr_contract_44_fz_unclear") == E.TERMINAL_NO_RESULT
    assert norm(source_table="reestr_contract_44_fz_completed") == E.TERMINAL_NO_RESULT
    assert norm(source_table="reestr_contract_44_fz_unknown") == E.TERMINAL_NO_RESULT
    assert norm(source_table="reestr_contract_223_fz_completed") == E.TERMINAL_NO_RESULT


def test_unknown_table_fail_closed():
    assert norm(source_table="something_else") == E.UNKNOWN


def test_dates_never_change_result():
    for table in (
        "reestr_contract_44_fz", "reestr_contract_44_fz_commission_work",
        "reestr_contract_44_fz_awarded", "reestr_contract_44_fz_unclear",
        "reestr_contract_44_fz_completed",
    ):
        assert norm(source_table=table, end_date=PAST) == norm(source_table=table, end_date=FUTURE)


def test_no_date_authority_in_source():
    src = (Path(__file__).resolve().parents[1]
           / "src/services/commercial_routing_v3/source_lifecycle.py").read_text(
        encoding="utf-8", errors="replace")
    assert "deadline < today" not in src
    assert "end_date < as_of" not in src


def _run_all():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
