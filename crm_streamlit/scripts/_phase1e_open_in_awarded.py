#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from src.bootstrap import setup_source_path

setup_source_path()

from psycopg2.extras import RealDictCursor
import psycopg2

from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.db_bootstrap import connect_databases


def main() -> int:
    where = (
        "cp.crm_stage='torgi' AND cp.award_status='submission_open' AND "
        + actionable_submission_sql("cp")
    )
    _, tender, crm, _ = connect_databases()
    conn = psycopg2.connect(**require_crm_db_connect_kwargs())
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        f"""
        SELECT btrim(contract_number) AS cn
        FROM crm_procurements cp
        WHERE {where}
          AND source_table=%s
          AND contract_number IS NOT NULL AND btrim(contract_number)<>''
        """,
        ("reestr_contract_44_fz",),
    )
    cns = [r["cn"] for r in cur.fetchall()]
    print("OPEN44", len(cns))

    hits = 0
    samples = []
    for i in range(0, len(cns), 500):
        chunk = cns[i : i + 500]
        rows = tender.execute_query(
            "SELECT DISTINCT contract_number::text FROM reestr_contract_44_fz_awarded WHERE contract_number::text = ANY(%s)",
            (chunk,),
        )
        for r in rows or []:
            hits += 1
            val = r[0] if not isinstance(r, dict) else list(r.values())[0]
            if len(samples) < 8:
                samples.append(val)
    print("OPEN44_IN_SOURCE_AWARDED", hits)
    print("SAMPLES", samples)

    hits2 = 0
    samples2 = []
    for i in range(0, len(cns), 500):
        chunk = cns[i : i + 500]
        rows = tender.execute_query(
            "SELECT DISTINCT contract_number::text FROM reestr_contract_44_fz_commission_work WHERE contract_number::text = ANY(%s)",
            (chunk,),
        )
        for r in rows or []:
            hits2 += 1
            val = r[0] if not isinstance(r, dict) else list(r.values())[0]
            if len(samples2) < 5:
                samples2.append(val)
    print("OPEN44_IN_SOURCE_COMMISSION", hits2, samples2)

    cur.execute(
        f"""
        SELECT btrim(contract_number) AS cn
        FROM crm_procurements cp
        WHERE {where}
          AND source_table=%s
          AND contract_number IS NOT NULL AND btrim(contract_number)<>''
        """,
        ("reestr_contract_223_fz",),
    )
    cns223 = [r["cn"] for r in cur.fetchall()]
    print("OPEN223", len(cns223))
    print(
        "SOURCE_223_AWARDED_COUNT",
        tender.execute_query("SELECT COUNT(*) FROM reestr_contract_223_fz_awarded")[0][0],
    )
    print(
        "SOURCE_615_COUNT",
        tender.execute_query("SELECT COUNT(*) FROM reestr_contract_615_pp")[0][0],
    )
    print(
        "CRM_615_COUNT",
        crm.execute_query(
            "SELECT COUNT(*) AS c FROM crm_procurements WHERE source_table ILIKE %s",
            ("%615%",),
        )[0]["c"],
    )

    # Detail for awarded samples still in UI torgi
    if samples:
        cur.execute(
            f"""
            SELECT id, contract_number, source_table, source_id, end_date, crm_stage, award_status,
                   left(auction_name,70) AS title
            FROM crm_procurements cp
            WHERE {where} AND btrim(contract_number) = ANY(%s)
            ORDER BY end_date
            LIMIT 10
            """,
            (samples,),
        )
        print("CONTROL_ROWS")
        for r in cur.fetchall():
            print(dict(r))
            # source awarded id
            arows = tender.execute_query(
                """
                SELECT id, contract_number, end_date, left(auction_name,60)
                FROM reestr_contract_44_fz_awarded
                WHERE contract_number::text = %s
                LIMIT 3
                """,
                (r["contract_number"],),
            )
            print("  SOURCE_AWARDED", arows)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
