#!/usr/bin/env python3
"""Extra lifecycle invariant counts for closure report."""
from __future__ import annotations

from src.db import get_connection
from src.services.effective_lifecycle import (
    LAW_615_IN_ANALYTICS_WORKSET,
    LAW_615_MISSING_PATH,
    factual_awarded_sql,
    factual_commission_sql,
    factual_open_torgi_sql,
    law_filter_sql,
)


def main() -> None:
    conn = get_connection()
    cur = conn.cursor()

    def one(sql: str, params=None):
        cur.execute(sql, params or ())
        return cur.fetchone()[0]

    open_sql = factual_open_torgi_sql("p")
    open_t = factual_open_torgi_sql("t")
    open_c = factual_commission_sql("c")
    open_a = factual_awarded_sql("a")
    comm_p = factual_commission_sql("p")
    aw_p = factual_awarded_sql("p")

    print("COMMISSION_IN_TORGI", one(f"SELECT COUNT(*) FROM crm_procurements p WHERE {open_sql} AND {comm_p}"))
    print("AWARDED_IN_TORGI_DOUBLECHECK", one(f"SELECT COUNT(*) FROM crm_procurements p WHERE {open_sql} AND {aw_p}"))
    print(
        "SAME_CN_TORGI_COMM",
        one(
            f"""
            SELECT COUNT(*) FROM (
              SELECT DISTINCT NULLIF(BTRIM(t.contract_number),'') cn
              FROM crm_procurements t
              JOIN crm_procurements c
                ON NULLIF(BTRIM(t.contract_number),'') = NULLIF(BTRIM(c.contract_number),'')
              WHERE {open_t} AND {open_c}
            ) x
            """
        ),
    )
    print(
        "SAME_CN_TORGI_AW",
        one(
            f"""
            SELECT COUNT(*) FROM (
              SELECT DISTINCT NULLIF(BTRIM(t.contract_number),'') cn
              FROM crm_procurements t
              JOIN crm_procurements a
                ON NULLIF(BTRIM(t.contract_number),'') = NULLIF(BTRIM(a.contract_number),'')
              WHERE {open_t} AND {open_a}
            ) x
            """
        ),
    )
    print(
        "SAME_CN_COMM_AW",
        one(
            f"""
            SELECT COUNT(*) FROM (
              SELECT DISTINCT NULLIF(BTRIM(c.contract_number),'') cn
              FROM crm_procurements c
              JOIN crm_procurements a
                ON NULLIF(BTRIM(c.contract_number),'') = NULLIF(BTRIM(a.contract_number),'')
              WHERE {open_c} AND {open_a}
            ) x
            """
        ),
    )
    print("LAW_615_IN_ANALYTICS_WORKSET", LAW_615_IN_ANALYTICS_WORKSET)
    print("LAW_615_MISSING_PATH", LAW_615_MISSING_PATH)
    print("UI44", one(f"SELECT COUNT(*) FROM crm_procurements p WHERE {open_sql} AND ({law_filter_sql('44', 'p')})"))
    print("UI223", one(f"SELECT COUNT(*) FROM crm_procurements p WHERE {open_sql} AND ({law_filter_sql('223', 'p')})"))
    print("UI615", one(f"SELECT COUNT(*) FROM crm_procurements p WHERE {open_sql} AND ({law_filter_sql('615', 'p')})"))
    print(
        "NULL_DEADLINE_STILL_LABELED_OPEN",
        one(
            """
            SELECT COUNT(*) FROM crm_procurements
            WHERE crm_stage='torgi' AND award_status='submission_open' AND end_date IS NULL
            """
        ),
    )
    print(
        "NULL_DEADLINE_IN_FACTUAL_TORGI",
        one(f"SELECT COUNT(*) FROM crm_procurements p WHERE {open_sql} AND p.end_date IS NULL"),
    )
    print(
        "CREATED_TODAY_IN_FACTUAL",
        one(f"SELECT COUNT(*) FROM crm_procurements p WHERE {open_sql} AND p.created_at::date = CURRENT_DATE"),
    )
    print(
        "CREATED_BEFORE_TODAY_IN_FACTUAL",
        one(f"SELECT COUNT(*) FROM crm_procurements p WHERE {open_sql} AND p.created_at::date < CURRENT_DATE"),
    )
    print(
        "RAW_SUBMISSION_OPEN_ROWS",
        one(
            "SELECT COUNT(*) FROM crm_procurements WHERE crm_stage='torgi' AND award_status='submission_open'"
        ),
    )
    cur.execute(
        """
        SELECT source_table, crm_stage, award_status, COUNT(*)
        FROM crm_procurements
        GROUP BY 1,2,3
        ORDER BY 4 DESC
        LIMIT 20
        """
    )
    print("TOP_CRM_GROUPS")
    for row in cur.fetchall():
        print(" ", row)
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
