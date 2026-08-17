from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
S7 = REPO / "eis_ingestion" / "s7_forward"
TAGS = S7 / "required_tags"


def test_unified_lookup_sql_parenthesizes_limit_per_branch():
    sys.path.insert(0, str(S7))
    from database_work.contract_registry_locator import build_unified_lookup_sql

    sql = build_unified_lookup_sql(
        ["reestr_contract_44_fz", "reestr_contract_44_fz_awarded"]
    )
    assert "LIMIT 1 UNION ALL" not in sql
    assert sql.count("(SELECT id") == 2
    assert sql.endswith(") candidates ORDER BY priority LIMIT 1")


def test_223_mapping_invariants_unchanged():
    notice = json.loads((TAGS / "required_tags_223_fz.json").read_text(encoding="utf-8"))
    recouped = json.loads(
        (TAGS / "required_tags_223_fz_recouped.json").read_text(encoding="utf-8")
    )
    contract = recouped["reestr_contract"]
    assert notice["reestr_contract"]["end_date"] == "submissionCloseDateTime"
    assert contract["contract_number"] == (
        "contractData/purchaseNoticeInfo/purchaseNoticeNumber"
    )
    assert contract["delivery_start_date"] == "contractData/startExecutionDate"
    assert contract["delivery_end_date"] == "contractData/endExecutionDate"
    assert contract["final_price"] == "contractData/price"
    assert "unitPrice" not in json.dumps(recouped)
    assert "documentationDelivery" not in json.dumps(notice)
    assert "documentationDelivery" not in json.dumps(recouped)


def test_metrics_emit_one_json_line(tmp_path, monkeypatch):
    sys.path.insert(0, str(S7))
    metrics_file = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("TENDERMONITOR_METRICS_FILE", str(metrics_file))
    from utils.source_day_metrics import emit

    emit("region_complete", source_date="2026-08-12", region="16", elapsed_sec=1.5)
    lines = metrics_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "region_complete"
    assert payload["region"] == "16"
    assert "ts" in payload


def test_okpd_debug_prints_default_off(monkeypatch):
    sys.path.insert(0, str(S7))
    monkeypatch.delenv("TENDERMONITOR_DEBUG_PRINTS", raising=False)
    import parsing_xml.okpd_parser as okpd_parser

    captured = []

    def fake_print(*args, **kwargs):
        captured.append(args)

    monkeypatch.setattr("builtins.print", fake_print)
    okpd_parser._dprint("DEBUG: should stay silent")
    assert captured == []
    monkeypatch.setenv("TENDERMONITOR_DEBUG_PRINTS", "1")
    okpd_parser._dprint("DEBUG: visible")
    assert captured == [("DEBUG: visible",)]
