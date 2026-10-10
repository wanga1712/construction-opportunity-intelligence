"""Пересчёт медалей прямых поставок по стоимостному порогу (согласовано 10.10.2026).

Правило: НМЦК ≤ 10 000 ₽ → не выше WOOD, < 50 000 ₽ → BRONZE, < 100 000 ₽ → SILVER,
≥ 100 000 ₽ → без ограничения (см. src/services/commercial_routing_v3/direct_value_floor.py).
Медаль может только понижаться; баллы подрезаются до верхней границы полосы, чтобы
число и медаль не противоречили друг другу.

usage:
    python scripts/recompute_direct_value_medals.py            # dry-run
    python scripts/recompute_direct_value_medals.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from typing import Any, Dict, List

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.domain.commercial_routing_v3 import CandidateMedal
from src.services.commercial_routing_v3.direct_value_floor import (
    direct_value_cap,
    medal_rank,
)
from src.services.crm_db_runtime import require_crm_db_connect_kwargs

BAND_TOP = {CandidateMedal.WOOD: 24, CandidateMedal.BRONZE: 49, CandidateMedal.SILVER: 74}


def load_rows(conn) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT o.id, o.procurement_id, o.current_effective_medal, o.candidate_medal,
                      o.candidate_initial_medal, o.current_effective_reason,
                      o.commercial_priority_score, o.research_value_score,
                      o.candidate_initial_score, o.current_effective_score,
                      p.initial_price, p.contract_number
               FROM crm_procurement_category_opportunities o
               JOIN crm_procurements p ON p.id = o.procurement_id
               WHERE upper(coalesce(o.opportunity_track, '')) = 'DIRECT_SUPPLY'"""
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(**dict(require_crm_db_connect_kwargs()))
    try:
        rows = load_rows(conn)
        changes = []
        for row in rows:
            cap, reason = direct_value_cap(row.get("initial_price"))
            if cap is None:
                continue
            current = str(row.get("current_effective_medal") or "").upper()
            try:
                current_enum = CandidateMedal(current)
            except ValueError:
                continue
            if medal_rank(cap) >= medal_rank(current_enum):
                continue
            changes.append({"row": row, "cap": cap, "reason": reason, "from": current})
        transitions = Counter("%s→%s" % (c["from"], c["cap"].value) for c in changes)
        print("direct_current=%d affected=%d" % (len(rows), len(changes)))
        print("transitions: %s" % dict(transitions))
        print("примеры:")
        for change in changes[:8]:
            row = change["row"]
            print("   %s pid=%s НМЦК=%s: %s→%s (%s)" % (
                row.get("contract_number"), row.get("procurement_id"),
                row.get("initial_price"), change["from"], change["cap"].value, change["reason"]))
        if not args.apply:
            print("DRY-RUN: изменения не применены (--apply)")
            return 0
        with conn.cursor() as cur:
            for change in changes:
                row = change["row"]
                cap = change["cap"]
                top = BAND_TOP.get(cap, 0)
                cur.execute(
                    """UPDATE crm_procurement_category_opportunities
                          SET current_effective_medal = %s,
                              candidate_medal = CASE WHEN %s < CASE upper(coalesce(candidate_medal,''))
                                                     WHEN 'GOLD' THEN 4 WHEN 'SILVER' THEN 3
                                                     WHEN 'BRONZE' THEN 2 WHEN 'WOOD' THEN 1 ELSE 0 END
                                                  THEN candidate_medal ELSE %s END,
                              candidate_initial_medal = CASE
                                  WHEN %s < CASE upper(coalesce(candidate_initial_medal,''))
                                              WHEN 'GOLD' THEN 4 WHEN 'SILVER' THEN 3
                                              WHEN 'BRONZE' THEN 2 WHEN 'WOOD' THEN 1 ELSE 0 END
                                       THEN candidate_initial_medal ELSE %s END,
                              current_effective_reason = %s,
                              commercial_priority_score = LEAST(coalesce(commercial_priority_score, 0), %s),
                              research_value_score = LEAST(coalesce(research_value_score, 0), %s),
                              candidate_initial_score = LEAST(coalesce(candidate_initial_score, 0), %s),
                              current_effective_score = LEAST(coalesce(current_effective_score, 0), %s),
                              updated_at = NOW()
                        WHERE id = %s""",
                    (cap.value, 4 - medal_rank(cap), cap.value,
                     4 - medal_rank(cap), cap.value, change["reason"],
                     top, top, top, top, row["id"]),
                )
        conn.commit()
        print("APPLIED: обновлено %d возможностей" % len(changes))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
