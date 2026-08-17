#!/usr/bin/env python3
"""Deterministic daily medal reevaluation. No Qwen.

Default dry-run. Production apply: --apply (writes current_effective_* + history).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.daily_medal_reevaluation import (
    DAILY_REEVALUATION_VERSION,
    PROPOSED_PRODUCTION_CADENCE,
    reevaluate_many,
)
from src.services.commercial_routing_v3.opportunity_persistence import (
    persist_current_effective_lineage,
    persist_medal_history_rows,
)
from src.services.commercial_routing_v3.source_lifecycle import (
    normalize_source_lifecycle_event,
)
from src.services.db_bootstrap import connect_databases

OUT = Path("/var/lib/crm-v3-canary/continuous_production_startup")


def main() -> int:
    parser = argparse.ArgumentParser(description="V3 daily medal reevaluation (no Qwen)")
    parser.add_argument("--apply", action="store_true", help="Persist current_effective + history")
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    dry_run = not args.apply

    _r, _t, crm_db, _w = connect_databases()
    rows = crm_db.execute_query(
        """
        SELECT o.procurement_id, o.commercial_category_code, o.opportunity_track,
               o.procurement_form, o.candidate_medal,
               o.candidate_initial_medal, o.candidate_initial_score,
               o.confirmed_base_medal, o.confirmed_base_score,
               o.current_effective_medal, o.current_effective_score,
               o.semantic_hypothesis, o.initial_medal_provenance,
               p.source_table, p.crm_stage, p.award_status, p.end_date,
               p.initial_price, p.award_date
        FROM crm_procurement_category_opportunities o
        JOIN crm_procurements p ON p.id = o.procurement_id
        WHERE o.status = 'CURRENT'
        ORDER BY o.procurement_id
        LIMIT %s
        """,
        (args.limit,),
    ) or []

    mapped = []
    for r in rows:
        hyp = r.get("semantic_hypothesis") or {}
        if isinstance(hyp, str):
            hyp = {}
        lc = normalize_source_lifecycle_event(
            source_table=str(r.get("source_table") or ""),
            crm_stage=str(r.get("crm_stage") or ""),
            award_status=str(r.get("award_status") or ""),
            end_date=r.get("end_date"),
        ).value
        mapped.append(
            {
                "procurement_id": r.get("procurement_id"),
                "commercial_category_code": r.get("commercial_category_code"),
                "opportunity_track": r.get("opportunity_track"),
                "lifecycle": lc,
                "normalized_lifecycle": lc,
                "procurement_form": r.get("procurement_form"),
                "candidate_initial_medal": r.get("candidate_initial_medal"),
                "candidate_initial_score": r.get("candidate_initial_score"),
                "confirmed_base_medal": r.get("confirmed_base_medal"),
                "confirmed_base_score": r.get("confirmed_base_score"),
                "current_effective_medal": r.get("current_effective_medal")
                or r.get("candidate_medal"),
                "current_effective_score": r.get("current_effective_score"),
                "semantic_hypothesis": hyp,
                "initial_medal_provenance": r.get("initial_medal_provenance"),
                "initial_price": r.get("initial_price"),
                "model_input": {
                    "initial_price": r.get("initial_price"),
                    "award_date": str(r.get("award_date") or "")[:10] or None,
                    "end_date": str(r.get("end_date") or "")[:10] or None,
                },
            }
        )

    out = reevaluate_many(mapped)
    written_lineage = 0
    written_history = 0
    if not dry_run:
        for row in mapped:
            if not row.get("current_effective_medal"):
                continue
            ok = persist_current_effective_lineage(
                crm_db,
                procurement_id=row.get("procurement_id"),
                commercial_category_code=str(row.get("commercial_category_code") or ""),
                opportunity_track=row.get("opportunity_track"),
                lineage=row,
                dry_run=False,
            )
            if ok:
                written_lineage += 1
        written_history = persist_medal_history_rows(
            crm_db, out["history_rows"], dry_run=False
        )

    payload = {
        "dry_run": dry_run,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "rows_loaded": len(mapped),
        "qwen_calls": out["qwen_calls"],
        "TIME_ONLY_REEVALUATION_QWEN_CALLS": out["qwen_calls"],
        "history_count": len(out["history_rows"]),
        "updated": out["updated"],
        "written_lineage": written_lineage,
        "written_history": written_history,
        "proposed_cadence": PROPOSED_PRODUCTION_CADENCE,
        "daily_reevaluation_version": DAILY_REEVALUATION_VERSION,
        "writes": not dry_run,
    }
    name = "daily_reevaluation_apply.json" if not dry_run else "daily_reevaluation_dry_run.json"
    (OUT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
