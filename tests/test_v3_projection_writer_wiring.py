"""Production wiring tests for V3 projection writer."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.services.commercial_routing_v3 import projection as proj
from src.services.commercial_routing_v3 import projection_writer as pw

ROOT = Path(__file__).resolve().parents[1]


def test_production_writer_constants():
    assert pw.PRODUCTION_PROJECTION_WRITER == "V3"
    assert pw.LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH is False
    assert pw.PARALLEL_LEGACY_PROJECTION_WRITER is False
    assert pw.PROJECTED_ROW_ACTIVE_LEAD is False
    assert pw.CROSS_CONTOUR_FALSE_DEDUPE is False
    assert proj.OPEN_REQUIRES_DOCS_PROCESSED is False
    assert proj.OPEN_REQUIRES_USER_OKPD is False
    assert proj.FULL_AWARDED_HISTORY_IMPORTED is False


def test_run_crm_sync_uses_v3_not_legacy():
    src = (ROOT / "scripts/run_crm_sync.py").read_text(encoding="utf-8")
    assert "run_v3_projection_sync" in src
    assert "PRODUCTION_PROJECTION_WRITER" in src
    assert "sync_all_processed(" not in src
    assert "LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH" in src


def test_open_waiting_awarded_same_id_in_memory():
    store = proj.InMemoryProjectionStore()
    cn = "CN-WIRE-1"
    r1, _ = proj.project_source_row(
        store,
        {"source_table": "reestr_contract_44_fz", "source_id": 1, "contract_number": cn, "auction_name": "A"},
        enabled=True,
    )
    r2, _ = proj.project_source_row(
        store,
        {
            "source_table": "reestr_contract_44_fz_commission_work",
            "source_id": 2,
            "contract_number": cn,
            "auction_name": "A",
        },
        enabled=True,
    )
    r3, _ = proj.project_source_row(
        store,
        {
            "source_table": "reestr_contract_44_fz_awarded",
            "source_id": 3,
            "contract_number": cn,
            "auction_name": "A",
            "updated_at": datetime.now(timezone.utc),
        },
        enabled=True,
        crm_has_lifecycle_identity=True,
    )
    assert r1["id"] == r2["id"] == r3["id"]


def test_cross_contour_not_deduped():
    store = proj.InMemoryProjectionStore()
    cn = "SAME-CN"
    a, _ = proj.project_source_row(
        store,
        {"source_table": "reestr_contract_44_fz", "source_id": 10, "contract_number": cn, "auction_name": "T"},
        enabled=True,
    )
    b, _ = proj.project_source_row(
        store,
        {"source_table": "reestr_contract_223_fz", "source_id": 11, "contract_number": cn, "auction_name": "T"},
        enabled=True,
    )
    assert a["id"] != b["id"]
    assert len(store.rows) == 2


def test_missing_contract_fallback_safe():
    store = proj.InMemoryProjectionStore()
    a, d1 = proj.project_source_row(
        store,
        {"source_table": "reestr_contract_44_fz", "source_id": 99, "contract_number": "", "auction_name": "T"},
        enabled=True,
    )
    assert d1.admit
    assert a is not None
    b, _ = proj.project_source_row(
        store,
        {"source_table": "reestr_contract_44_fz", "source_id": 99, "contract_number": None, "auction_name": "T"},
        enabled=True,
    )
    assert a["id"] == b["id"]


def test_no_docs_processed_gate_in_admission():
    d = proj.admit_source_row(
        source_table="reestr_contract_44_fz",
        source_id=1,
        contract_number="X",
        auction_name="Title",
        enabled=True,
    )
    assert d.admit is True


def test_dedupe_prefers_awarded_stage():
    rows = [
        {"source_table": "reestr_contract_44_fz", "source_id": 1, "contract_number": "C1", "auction_name": "T"},
        {
            "source_table": "reestr_contract_44_fz_awarded",
            "source_id": 9,
            "contract_number": "C1",
            "auction_name": "T",
        },
    ]
    out = pw._dedupe_by_lifecycle(rows)
    assert len(out) == 1
    assert out[0]["source_table"].endswith("awarded")
