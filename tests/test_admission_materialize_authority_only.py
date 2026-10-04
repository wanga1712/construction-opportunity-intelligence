"""PHASE 3: admission_gate_materialize --authority-only must not touch the queue
and must re-materialise existing authority rows (stale lifecycle refresh)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SRC = (ROOT / "scripts" / "admission_gate_materialize.py").read_text(
    encoding="utf-8", errors="replace"
)


def test_authority_only_flag_exists():
    assert "--authority-only" in SRC
    assert "authority_only" in SRC


def test_authority_only_skips_queue():
    # reconcile_queue is only invoked when NOT authority-only
    assert "if args.authority_only:" in SRC
    assert "QUEUE_UPDATE_CALLS=0" in SRC


def test_selector_includes_existing_authority_ids():
    assert "SELECT procurement_id FROM crm_procurement_scope_authority" in SRC


def test_lifecycle_is_table_authoritative():
    from src.domain.commercial_opportunity_lifecycle import SourceLifecycleEvent as E
    from src.services.commercial_routing_v3.source_lifecycle import (
        normalize_source_lifecycle_event as norm,
    )

    # stale MAIN row with a past end_date must be OPEN, not WAITING
    assert norm(source_table="reestr_contract_44_fz", end_date="2000-01-01") == E.OPEN
    assert norm(source_table="reestr_contract_223_fz", end_date="2000-01-01") == E.OPEN


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
