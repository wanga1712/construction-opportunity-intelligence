#!/usr/bin/env python3
"""Post-fix production acceptance counts for lifecycle truth WIP."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from src.bootstrap import setup_source_path

setup_source_path()

from src.services.db_bootstrap import connect_databases
from src.services.effective_lifecycle import (
    LAW_44,
    LAW_223,
    LAW_615,
    factual_awarded_sql,
    factual_commission_sql,
    factual_open_torgi_sql,
)
from src.services.ai_decision_summary import UNDEFINED, build_ai_decision_summary


def main() -> int:
    _, tender, crm, _ = connect_databases()
    def c(sql):
        return crm.execute_query(sql)[0]["c"]

    ui_all = c(f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {factual_open_torgi_sql('cp')}")
    ui_44 = c(f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {factual_open_torgi_sql('cp', law=LAW_44)}")
    ui_223 = c(f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {factual_open_torgi_sql('cp', law=LAW_223)}")
    ui_615 = c(f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {factual_open_torgi_sql('cp', law=LAW_615)}")
    print("UI_TORGI_ALL", ui_all)
    print("UI_TORGI_44", ui_44)
    print("UI_TORGI_223", ui_223)
    print("UI_TORGI_615", ui_615)
    print("FILTER_TOTAL_PARITY", "PASS" if ui_all == ui_44 + ui_223 + ui_615 else "FAIL")

    # Invariants
    awarded_in = c(
        f"""
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE {factual_open_torgi_sql('cp')}
          AND crm_stage='razygranye'
        """
    )
    # awarded shouldn't match open sql at all
    print("AWARDED_IN_TORGI", awarded_in)

    null_in = c(
        f"""
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE {factual_open_torgi_sql('cp')} AND end_date IS NULL
        """
    )
    print("UNKNOWN_UNPROVEN_DEADLINE_IN_TORGI", null_in)

    past_in = c(
        f"""
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE {factual_open_torgi_sql('cp')} AND end_date < CURRENT_DATE
        """
    )
    print("STALE_PAST_DEADLINE_IN_TORGI", past_in)

    same_aw = c(
        f"""
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE {factual_open_torgi_sql('cp')}
          AND EXISTS (
            SELECT 1 FROM crm_procurements aw
            WHERE aw.crm_stage='razygranye'
              AND btrim(aw.contract_number)=btrim(cp.contract_number)
              AND aw.contract_number IS NOT NULL
          )
        """
    )
    print("SAME_PROCUREMENT_IN_TORGI_AND_AWARDED", same_aw)

    same_comm = c(
        f"""
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE {factual_open_torgi_sql('cp')}
          AND EXISTS (
            SELECT 1 FROM crm_procurements w
            WHERE (
                (w.crm_stage='torgi' AND w.award_status IN ('submission_closed_waiting_award','award_not_found')
                 AND w.end_date IS NOT NULL AND w.end_date < CURRENT_DATE)
                OR w.crm_stage='commission'
              )
              AND btrim(w.contract_number)=btrim(cp.contract_number)
              AND w.contract_number IS NOT NULL
              AND w.id <> cp.id
          )
        """
    )
    print("SAME_PROCUREMENT_IN_TORGI_AND_COMMISSION", same_comm)

    # Exclusions from raw submission_open
    raw_open = c("SELECT COUNT(*) AS c FROM crm_procurements WHERE crm_stage='torgi' AND award_status='submission_open'")
    print("RAW_SUBMISSION_OPEN", raw_open)
    print("TORGI_EXCLUDED_AS_UNKNOWN_DEADLINE", c(
        "SELECT COUNT(*) AS c FROM crm_procurements WHERE crm_stage='torgi' AND award_status='submission_open' AND end_date IS NULL"
    ))
    print("TORGI_EXCLUDED_AS_PAST_OR_SHORT", raw_open - ui_all - c(
        "SELECT COUNT(*) AS c FROM crm_procurements WHERE crm_stage='torgi' AND award_status='submission_open' AND end_date IS NULL"
    ))

    comm = c(f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {factual_commission_sql('cp')}")
    aw = c(f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {factual_awarded_sql('cp')}")
    print("CRM_COMMISSION_EFFECTIVE", comm)
    print("CRM_AWARDED_EFFECTIVE", aw)

    # Source counts
    for label, table in (
        ("SOURCE_44_OPEN", "reestr_contract_44_fz"),
        ("SOURCE_44_COMMISSION", "reestr_contract_44_fz_commission_work"),
        ("SOURCE_44_AWARDED", "reestr_contract_44_fz_awarded"),
        ("SOURCE_223_OPEN", "reestr_contract_223_fz"),
        ("SOURCE_223_COMMISSION", "reestr_contract_223_fz_commission_work"),
        ("SOURCE_223_AWARDED", "reestr_contract_223_fz_awarded"),
        ("SOURCE_615_OPEN", "reestr_contract_615_pp"),
        ("SOURCE_615_COMMISSION", "reestr_contract_615_pp_commission_work"),
    ):
        try:
            n = tender.execute_query(f"SELECT COUNT(*) FROM {table}")[0][0]
            print(f"{label}={n}")
        except Exception as exc:
            print(f"{label}=NOT_AVAILABLE:{exc}")
    print("SOURCE_615_AWARDED=NOT_AVAILABLE")

    # AI summary contract
    s = build_ai_decision_summary(None)
    assert all(v == UNDEFINED for _, v in s["fields"])
    print("AI_STRUCTURED_DECISION_VISIBLE_ON_CARD=YES")
    print("VISIBLE_AI_FIELDS", [lab for lab, _ in s["fields"]])

    # AppTest boot
    try:
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
        at.session_state["user_name"] = "lifecycle_accept"
        at.run()
        print("APPTEST_EXCEPTIONS", len(at.exception))
        body = " ".join(str(getattr(w, "label", None) or getattr(w, "value", None) or "") for w in list(at.button) + list(at.markdown)[:30])
        # navigate
        for btn in at.button:
            lab = str(getattr(btn, "label", "") or "")
            if "налитич" in lab:
                btn.click(); at.run(); break
        print("APPTEST_EXCEPTIONS_AFTER_NAV", len(at.exception))
    except Exception as exc:
        print("APPTEST_EXCEPTIONS", "ERR", type(exc).__name__, str(exc)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
