#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from src.bootstrap import setup_source_path

setup_source_path()

from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
from src.services.db_bootstrap import connect_databases


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def main() -> int:
    _, tender, crm, _ = connect_databases()
    where = (
        "cp.crm_stage='torgi' AND cp.award_status='submission_open' AND "
        + actionable_submission_sql("cp")
    )
    rows = crm.execute_query(
        f"""
        SELECT btrim(contract_number) AS cn
        FROM crm_procurements cp
        WHERE {where} AND source_table=%s AND contract_number IS NOT NULL
        """,
        ("reestr_contract_44_fz",),
    )
    cns = [r["cn"] for r in rows]
    print("OPEN44", len(cns), "sample", cns[:5])
    arows = tender.execute_query(
        "SELECT contract_number::text FROM reestr_contract_44_fz_awarded WHERE contract_number IS NOT NULL LIMIT 5"
    )
    print("AW_SAMPLE", arows)

    # Exact
    hits = tender.execute_query(
        "SELECT COUNT(*) FROM reestr_contract_44_fz_awarded WHERE contract_number::text = ANY(%s)",
        (cns,),
    )[0][0]
    print("EXACT_HITS", hits)

    # Digit-normalized: load awarded digit map for sample of CRM
    sample = cns[:300]
    awarded = tender.execute_query(
        "SELECT contract_number::text FROM reestr_contract_44_fz_awarded WHERE contract_number IS NOT NULL"
    )
    awarded_digits = {digits(r[0] if not isinstance(r, dict) else list(r.values())[0]) for r in awarded}
    awarded_digits.discard("")
    dig_hits = sum(1 for cn in sample if digits(cn) in awarded_digits)
    print("DIGIT_HITS_IN_300", dig_hits, "AWARDED_DIGIT_KEYS", len(awarded_digits))

    # How many CRM open have end_date far future (>180d) — possible stale
    far = crm.execute_query(
        f"""
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE {where} AND end_date > CURRENT_DATE + INTERVAL '180 days'
        """
    )[0]["c"]
    print("ACTIONABLE_END_OVER_180D", far)

    # AI assessed among actionable
    ai = crm.execute_query(
        f"""
        SELECT COALESCE(ai_assessment_status,'NULL') AS s, COUNT(*) AS c
        FROM crm_procurements cp
        WHERE {where}
        GROUP BY 1 ORDER BY c DESC
        """
    )
    print("AI_STATUS", [dict(r) for r in ai])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
